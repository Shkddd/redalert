"""
PDF 解析: 文本 + 图片 + 章节
用 pymupdf 主路径,pdfplumber 兜底

输出统一为 Page dataclass 列表:
  - text: 该页文本(可能有跨页段落合并)
  - images: 该页抽出的图片(bytes + 元数据)
  - section_path: 该页所属章节(根据 TOC + 启发式推断)
  - page_no: 1-indexed

旧接口(parse_pdf / parse_excel / parse)继续保留以兼容 pipeline。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import fitz  # pymupdf


# ============================================================
# 数据结构
# ============================================================
@dataclass
class ExtractedImage:
    image_id: str  # 暂存 uuid,由 pipeline 阶段存对象存储后再赋值
    page_no: int
    bytes: bytes
    mime: str
    width: int
    height: int
    bbox: Optional[Tuple[float, float, float, float]] = None  # x0,y0,x1,y1


@dataclass
class Page:
    page_no: int
    text: str
    images: List[ExtractedImage] = field(default_factory=list)
    section_path: str = ""
    raw_meta: Dict = field(default_factory=dict)


# ============================================================
# 工具
# ============================================================
_MIN_IMAGE_PX = 50  # 小于该尺寸的图(logo/分隔线)丢弃
_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20MB 单图上限


def _clean_text(t: str) -> str:
    if not t:
        return ""
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def _build_section_index(doc) -> List[Tuple[int, str]]:
    """
    用 TOC + 字号启发式构建 (page_no -> section_path) 索引
    TOC 例子: [[level, title, page], ...]
    字号启发式: 文本字号 > 1.4 * 中位字号 的行视为标题
    """
    sections_by_page: Dict[int, str] = {}

    # 1. TOC(大纲/书签)
    toc = doc.get_toc(simple=True) or []
    for level, title, page in toc:
        title = (title or "").strip()
        if not title:
            continue
        prefix = " > ".join(t for _, t, _ in toc if _ <= level and t) if False else title
        # 简化: 同一 page 用最近一级标题
        existing = sections_by_page.get(page, "")
        if existing:
            sections_by_page[page] = f"{existing} > {title}" if level > 1 else title
        else:
            sections_by_page[page] = title

    # 2. 字号启发式补充
    if not sections_by_page:
        for pi in range(len(doc)):
            page = doc[pi]
            blocks = page.get_text("dict")["blocks"]
            sizes = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for ln in b.get("lines", []):
                    for sp in ln.get("spans", []):
                        sz = sp.get("size", 0)
                        if sz > 0:
                            sizes.append(sz)
            if not sizes:
                continue
            sizes.sort()
            median = sizes[len(sizes) // 2]
            # 找最大字号段
            candidates = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for ln in b.get("lines", []):
                    txt = "".join(sp.get("text", "") for sp in ln.get("spans", []))
                    if not txt.strip():
                        continue
                    line_max_sz = max((sp.get("size", 0) for sp in ln.get("spans", [])), default=0)
                    if line_max_sz > median * 1.3 and len(txt.strip()) < 60:
                        candidates.append(txt.strip())
            if candidates and (pi + 1) not in sections_by_page:
                sections_by_page[pi + 1] = candidates[0]

    # 3. 推断每页章节: 如果该页没标,继承上一页
    resolved: List[Tuple[int, str]] = []
    cur = ""
    for i in range(1, len(doc) + 1):
        if i in sections_by_page:
            cur = sections_by_page[i]
        resolved.append((i, cur))
    return resolved


def _extract_images_from_page(doc, page, page_no: int) -> List[ExtractedImage]:
    """抽一页里所有图片(去重去小)"""
    out: List[ExtractedImage] = []
    seen_xref = set()
    try:
        images = page.get_images(full=True)
    except Exception:
        return out
    for img_info in images:
        xref = img_info[0]
        if xref in seen_xref:
            continue
        seen_xref.add(xref)
        try:
            base = doc.extract_image(xref)
        except Exception:
            continue
        data = base.get("image")
        if not data or len(data) > _MAX_IMAGE_BYTES:
            continue
        w = base.get("width", 0)
        h = base.get("height", 0)
        if w < _MIN_IMAGE_PX or h < _MIN_IMAGE_PX:
            continue
        mime = base.get("ext", "png")
        mime = f"image/{mime}" if mime in ("png", "jpg", "jpeg", "bmp", "gif", "webp") else "image/png"
        # bbox 找图在页面上的位置
        bbox = None
        try:
            rects = page.get_image_rects(xref)
            if rects:
                r = rects[0]
                bbox = (r.x0, r.y0, r.x1, r.y1)
        except Exception:
            pass
        out.append(ExtractedImage(
            image_id="",  # pipeline 阶段填
            page_no=page_no,
            bytes=data,
            mime=mime,
            width=w,
            height=h,
            bbox=bbox,
        ))
    return out


# ============================================================
# 主入口
# ============================================================
def parse_pdf(path: Path, extract_images: bool = True) -> List[Page]:
    """返回 List[Page], 含 text + images + section_path"""
    path = Path(path)
    doc = fitz.open(str(path))
    try:
        section_index = _build_section_index(doc)
        pages: List[Page] = []
        for i in range(len(doc)):
            page_no = i + 1
            page = doc[i]
            text = _clean_text(page.get_text("text"))
            images = _extract_images_from_page(doc, page, page_no) if extract_images else []
            section_path = ""
            for pn, sp in section_index:
                if pn == page_no:
                    section_path = sp
                    break
            pages.append(Page(
                page_no=page_no,
                text=text,
                images=images,
                section_path=section_path,
                raw_meta={"width": page.rect.width, "height": page.rect.height},
            ))
        return pages
    finally:
        doc.close()


def parse_pdf_text_only(path: Path) -> List[Dict]:
    """仅文本(快速路径, 给纯文本 PDF 或调试用)"""
    pages = parse_pdf(path, extract_images=False)
    return [{"page": p.page_no, "text": p.text, "section_path": p.section_path} for p in pages]


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    pages = parse_pdf(p)
    print(f"parsed {len(pages)} pages from {p.name}")
    for pg in pages[:3]:
        print(f"\n--- page {pg.page_no} | section: {pg.section_path} | images: {len(pg.images)} ---")
        print(pg.text[:200])
