"""
完整摄入管线:多格式解析→文本/图片切分→分类→摘要→向量化→写 Milvus+BM25+SQLite

流程:
  1. 解析: parser.parse(path) → List[Page]
  2. 文本 chunks: chunker.chunk_page(page, doc_title) for each page
  3. 图片处理:
     - 对每个 Page.images[i], 调 vision.describe_image 拿 caption
     - 降级: vision.fallback_caption(w, h, page_no)
     - 把图片 bytes 存 object_store → (image_id, url, abs_path)
     - 写 images 表
     - 生成"图片 chunk": text=caption, image_id/url/caption 字段填齐
  4. 合并文本 chunks + 图片 chunks
  5. 分类(classify), 摘要(summarize)
  6. 向量化(embed_texts)
  7. 写 SQLite chunks 表(含 doc_title/section_path/image_* 字段)
  8. 写 Milvus(payload 带新字段)
  9. 更新 BM25
"""
import hashlib
import shutil
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from app.core.config import UPLOAD_DIR, VERSION_DIR, OBJECT_STORE_DIR
from app.core.trace import stage, log, new_trace_id
from app.db.database import get_conn
from app.ingest.parser import parse, SUPPORTED_SUFFIXES
from app.ingest.parser_pdf import Page, ExtractedImage
from app.ingest.chunker import chunk_page
from app.ingest.classifier import classify_batch
from app.ingest.summarizer import summarize
from app.ingest.vision import describe_image, fallback_caption
from app.storage.object_store import save_bytes
from app.retrieval.embedder import embed_texts, insert_chunks, delete_by_doc_version
from app.retrieval import bm25_index


def _file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _process_page_images(page: Page, document_id: int, version_id: int,
                          trace_id: Optional[str] = None) -> List[dict]:
    """
    处理一页的所有图片:
      - 存到对象存储
      - 视觉 API 出说明
      - 写 images 表
      - 返回 "图片 chunks"(每个图一个 chunk)
    """
    image_chunks: List[dict] = []
    tid = trace_id or new_trace_id()
    log(tid, "image_process", "start", page_no=page.page_no,
        image_count=len(page.images))
    for idx, img in enumerate(page.images):
        img_idx = idx + 1
        log(tid, "image_process", "vision_start", page_no=img.page_no,
            image_idx=img_idx, mime=img.mime, bytes=len(img.bytes))
        t0 = time.time()
        # 1. 视觉 API 拿 caption
        caption = describe_image(img.bytes, img.mime)
        vision_ms = int((time.time() - t0) * 1000)
        used_fallback = False
        if caption:
            # 真实说明(非 fallback),视作成功
            log(tid, "image_process", "vision_ok", page_no=img.page_no,
                image_idx=img_idx, vision_ms=vision_ms,
                caption_len=len(caption),
                preview=caption[:80])
        else:
            # 走到这里是降级 — 说明 vision API 没成功
            caption = fallback_caption(img.width, img.height, img.page_no,
                                         filename=page.section_path, mime=img.mime)
            used_fallback = True
            log(tid, "image_process", "vision_fallback", page_no=img.page_no,
                image_idx=img_idx, vision_ms=vision_ms,
                reason="vision_returned_none",
                fallback_caption=caption)

        # 2. 存对象存储
        try:
            image_id, url, abs_path = save_bytes(img.bytes, mime=img.mime, doc_id=document_id)
            log(tid, "image_process", "object_store_ok", page_no=img.page_no,
                image_idx=img_idx, image_id=image_id, url=url, abs_path=abs_path)
        except Exception as e:
            # 极端情况存不上,跳过该图(但用占位 URL 防止 None)
            log(tid, "image_process", "object_store_fail", page_no=img.page_no,
                image_idx=img_idx,
                err=f"{type(e).__name__}: {str(e)[:200]}")
            image_id = ""
            url = ""

        # 3. 写 images 表
        if image_id:
            try:
                with get_conn() as conn:
                    conn.execute(
                        """INSERT INTO images (image_id, document_id, version_id,
                               page_no, section_path, mime, width, height,
                               byte_size, url, caption)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (image_id, document_id, version_id,
                         img.page_no, page.section_path,
                         img.mime, img.width, img.height,
                         len(img.bytes), url, caption),
                    )
                log(tid, "image_process", "images_table_ok", page_no=img.page_no,
                    image_idx=img_idx, image_id=image_id,
                    caption_len=len(caption))
            except Exception as e:
                log(tid, "image_process", "images_table_fail", page_no=img.page_no,
                    image_idx=img_idx,
                    err=f"{type(e).__name__}: {str(e)[:200]}")

        # 4. 构造图片 chunk
        image_chunks.append({
            "text": caption,
            "page": str(img.page_no),
            "page_no": img.page_no,
            "chunk_index": -1,  # 标记为图片
            "doc_title": "",  # pipeline 后填
            "section_path": page.section_path,
            "image_id": image_id,
            "image_caption": caption,
            "image_url": url,
        })
    log(tid, "image_process", "done", page_no=page.page_no,
        produced=len(image_chunks))
    return image_chunks


def ingest_file(file_path: Path, title: str, user_id: int,
                business_hint: str = None, change_note: str = None,
                trace_id: str = None) -> Dict:
    """摄入一个文件(多格式)"""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    trace_id = trace_id or new_trace_id()
    log(trace_id, "ingest", "receive", filename=file_path.name,
        suffix=file_path.suffix.lower(), user_id=user_id,
        title=title, business_hint=business_hint or "")

    src_hash = _file_hash(file_path)
    suffix = file_path.suffix.lower()
    log(trace_id, "ingest", "hash_computed", file_hash=src_hash)

    if suffix not in SUPPORTED_SUFFIXES:
        log(trace_id, "ingest", "reject", reason=f"unsupported suffix {suffix}")
        raise ValueError(f"unsupported file type: {suffix}")

    # 1. 落地到 uploads
    saved_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_path.name}"
    saved_path = UPLOAD_DIR / saved_name
    shutil.copy2(file_path, saved_path)
    log(trace_id, "ingest", "saved_to_uploads", path=str(saved_path))

    # 2. 找/建 document 记录
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, current_version FROM documents WHERE file_hash=?",
            (src_hash,),
        ).fetchone()

        if existing:
            doc_id = existing["id"]
            new_ver = existing["current_version"] + 1
            log(trace_id, "ingest", "doc_exists_new_version",
                doc_id=doc_id, version=new_ver)
        else:
            cur = conn.execute(
                """INSERT INTO documents (title, source_type, file_path, file_hash,
                                         uploaded_by, current_version)
                   VALUES (?,?,?,?,?,1)""",
                (title, suffix.lstrip("."), str(saved_path), src_hash, user_id),
            )
            doc_id = cur.lastrowid
            new_ver = 1
            log(trace_id, "ingest", "doc_created",
                doc_id=doc_id, version=new_ver, source_type=suffix.lstrip("."))

        # 3. 写 version
        cur = conn.execute(
            """INSERT INTO versions (document_id, version_no, file_path, file_hash, change_note, created_by)
               VALUES (?,?,?,?,?,?)""",
            (doc_id, new_ver, str(saved_path), src_hash, change_note or "", user_id),
        )
        version_id = cur.lastrowid

        conn.execute(
            "UPDATE documents SET current_version=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_ver, doc_id),
        )

    # 4. 解析 → List[Page]
    with stage(trace_id, "parse", file=str(file_path.name)):
        pages = parse(file_path)

    if not pages:
        log(trace_id, "ingest", "no_content", doc_id=doc_id, version_id=version_id)
        display_title = f"{title} v{new_ver}"
        return {"doc_id": doc_id, "version_id": version_id,
                "version_no": new_ver, "title": title,
                "display_title": display_title,
                "chunks": 0, "images": 0,
                "business_category": "通用", "business_domain": "通用",
                "summary": "", "updated_at": None,
                "trace_id": trace_id,
                "warning": "no content extracted"}

    total_images = sum(len(p.images) for p in pages)
    log(trace_id, "parse", "pages_extracted",
        pages=len(pages), total_images=total_images,
        page_sections=[p.section_path for p in pages[:5]])

    # 5. 切分文本 + 处理图片
    all_chunks: List[dict] = []
    image_total = 0

    with stage(trace_id, "chunk_and_image", pages=len(pages)):
        for page in pages:
            # 文本 chunks
            text_chunks = chunk_page(page, doc_title=title)
            all_chunks.extend(text_chunks)
            # 图片 chunks
            image_chunks = _process_page_images(page, doc_id, version_id,
                                                  trace_id=trace_id)
            all_chunks.extend(image_chunks)
            image_total += len(image_chunks)
            # 每页 trace
            log(trace_id, "page_processed", "ok",
                page_no=page.page_no,
                section=page.section_path or "",
                text_chunks=len(text_chunks),
                images=len(image_chunks),
                text_preview=(page.text or "")[:80])

    if not all_chunks:
        log(trace_id, "ingest", "no_chunks", doc_id=doc_id, version_id=version_id)
        display_title = f"{title} v{new_ver}"
        return {"doc_id": doc_id, "version_id": version_id,
                "version_no": new_ver, "title": title,
                "display_title": display_title,
                "chunks": 0, "images": 0,
                "business_category": "通用", "business_domain": "通用",
                "summary": "", "updated_at": None,
                "trace_id": trace_id,
                "warning": "chunker produced 0 chunks"}

    # 给图片 chunks 补 doc_title
    for c in all_chunks:
        if c.get("doc_title") == "":
            c["doc_title"] = title
    # 记录哪些 chunk 是图片(caption 直接当摘要,不走抽取)
    image_chunk_indices = {
        i for i, c in enumerate(all_chunks) if c.get("chunk_index") == -1
    }
    # 记录哪些 chunk 有预设摘要(CSV/Excel 结构化描述)
    preset_summaries = {}
    for i, c in enumerate(all_chunks):
        meta = c.get("raw_meta") or {}
        ps = meta.get("preset_summary")
        if ps:
            preset_summaries[i] = ps

    log(trace_id, "chunk", "done",
        text_chunks=len(all_chunks) - image_total,
        image_chunks=image_total,
        total=len(all_chunks))

    # 6. 分类
    with stage(trace_id, "classify", n=len(all_chunks)):
        texts = [c["text"] for c in all_chunks]
        categories = classify_batch(texts)
        from collections import Counter
        doc_category = Counter(categories).most_common(1)[0][0]
        if business_hint:
            doc_category = business_hint

    log(trace_id, "classify", "done",
        doc_category=doc_category,
        category_dist=dict(Counter(categories)))

    # 7. 摘要
    with stage(trace_id, "summarize", n=len(texts)):
        summaries = []
        for i, t in enumerate(texts):
            if i in image_chunk_indices:
                # 图片 chunk:caption 已经是完整描述,直接用
                summaries.append(t.strip())
            elif i in preset_summaries:
                # 结构化数据(CSV/Excel):用预设摘要,不走抽取
                summaries.append(preset_summaries[i])
            else:
                summaries.append(summarize(t, top_sent=2))

    # 8. 向量化
    with stage(trace_id, "embed", model="BAAI/bge-small-zh-v1.5", n=len(texts)):
        vecs = embed_texts(texts)
    log(trace_id, "embed", "vector_shape", shape=str(vecs.shape))

    # 9. 写 chunks 入库
    with stage(trace_id, "write_sqlite_chunks", n=len(all_chunks)):
        chunk_ids: List[int] = []
        with get_conn() as conn:
            for c, cat, summ in zip(all_chunks, categories, summaries):
                cur = conn.execute(
                    """INSERT INTO chunks (document_id, version_id, chunk_index, text,
                           summary, business_category, page_no,
                           doc_title, section_path, image_id, image_caption, image_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (doc_id, version_id, c["chunk_index"], c["text"], summ, cat,
                     c.get("page_no") or c.get("page"),
                     c.get("doc_title", ""), c.get("section_path", ""),
                     c.get("image_id") or None,
                     c.get("image_caption") or None,
                     c.get("image_url") or None),
                )
                chunk_ids.append(cur.lastrowid)

    # 10. 写 Milvus
    with stage(trace_id, "write_milvus", n=len(chunk_ids)):
        milvus_records = []
        for cid, c, v, cat in zip(chunk_ids, all_chunks, vecs, categories):
            milvus_records.append({
                "chunk_id": cid,
                "vector": v.tolist(),
                "text": c["text"],
                "document_id": doc_id,
                "version_id": version_id,
                "page": str(c.get("page_no") or c.get("page") or ""),
                "category": cat,
                "doc_title": c.get("doc_title", ""),
                "section_path": c.get("section_path", ""),
                "image_id": c.get("image_id") or "",
                "image_url": c.get("image_url") or "",
            })
        insert_chunks(milvus_records)

    # 11. 更新 BM25
    with stage(trace_id, "update_bm25", n=len(chunk_ids)):
        bm25_records = [{"chunk_id": cid, "text": c["text"]}
                        for cid, c in zip(chunk_ids, all_chunks)]
        bm25_index.build_or_update(doc_id, version_id, bm25_records)

    # 12. 更新 version.chunk_count + 文档业务分类
    with get_conn() as conn:
        conn.execute(
            "UPDATE versions SET chunk_count=? WHERE id=?",
            (len(chunk_ids), version_id),
        )
        conn.execute(
            """UPDATE documents SET business_category=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (doc_category, doc_id),
        )
        # 读出最终 updated_at(防止与其他写入竞争)
        row = conn.execute(
            "SELECT updated_at FROM documents WHERE id=?", (doc_id,),
        ).fetchone()
        updated_at_str = row["updated_at"] if row else None

    # 12.5 生成文档级 summary(把所有 chunk 的 summary 拼起来,前 N 字截断)
    # 优先取图片 chunk(summarize 出来通常有 caption),再补文本 chunk 摘要
    doc_summary = _make_doc_summary(summaries, texts, max_len=300)

    log(trace_id, "summary", "doc_level_done",
        summary_len=len(doc_summary),
        preview=doc_summary[:80])

    # 完整存储位置摘要
    log(trace_id, "ingest", "completed",
        doc_id=doc_id, version_id=version_id, version_no=new_ver,
        chunks=len(chunk_ids), images=image_total,
        business_category=doc_category,
        storage_layer="SQLite(chunks/images/versions/documents) + Milvus Lite + BM25",
        storage_paths={
            "uploads": str(saved_path),
            "object_store": OBJECT_STORE_DIR,
        },
        source_type=suffix.lstrip("."))

    return {
        "doc_id": doc_id,
        "version_id": version_id,
        "version_no": new_ver,
        "title": title,
        # 同名重复上传时,前端优先展示这个字段(title vN)
        "display_title": f"{title} v{new_ver}",
        "chunks": len(chunk_ids),
        "images": image_total,
        "business_category": doc_category,
        # 业务域别名(前端用哪个都行)
        "business_domain": doc_category,
        "summary": doc_summary,
        "updated_at": updated_at_str,
        "file_hash": src_hash,
        "source_type": suffix.lstrip("."),
        "trace_id": trace_id,
    }


def _make_doc_summary(summaries: list, texts: list, max_len: int = 300) -> str:
    """生成文档级摘要
    策略:
      - 把所有 chunk 的 summary 拼接, 用 "; " 分隔
      - 去重:分页 CSV/Excel 会产生 "xxx（第1部分）""xxx（第2部分）"，只保留一条
      - 超过 max_len 时截断 + "…"
    """
    import re
    parts = []
    seen_bases = set()
    # 优先有 summary 内容的(去掉空串/无内容)
    for s in summaries:
        if s and s.strip() and s.strip() != "(空)":
            s_clean = s.strip()
            # 分页摘要去重:"xxx（第N部分）" → 取 base 去重
            m = re.match(r"^(.+?)（第\d+部分）$", s_clean)
            base = m.group(1) if m else s_clean
            if base not in seen_bases:
                seen_bases.add(base)
                parts.append(base if m else s_clean)
        if sum(len(p) for p in parts) + len(parts) * 3 > max_len:
            break
    if parts:
        out = "; ".join(parts)
        if len(out) > max_len:
            out = out[:max_len - 1].rstrip() + "…"
        return out
    # 所有 summary 都空时,直接取文本前 max_len
    full = " ".join(t.strip() for t in texts if t and t.strip())
    return full[:max_len] if full else ""


def reingest_version(document_id: int, version_id: int, user_id: int):
    """重新处理某版本"""
    with get_conn() as conn:
        ver = conn.execute(
            "SELECT file_path, title, business_category FROM versions v JOIN documents d ON d.id=v.document_id WHERE v.id=?",
            (version_id,),
        ).fetchone()
    if not ver:
        raise ValueError("version not found")
    delete_by_doc_version(document_id, version_id)
    bm25_index.remove(document_id, version_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id=? AND version_id=?", (document_id, version_id))
        conn.execute("DELETE FROM images WHERE document_id=? AND version_id=?", (document_id, version_id))
    return ingest_file(Path(ver["file_path"]), ver["title"], user_id, business_hint=ver["business_category"])
