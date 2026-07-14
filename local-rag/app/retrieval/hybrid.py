"""
混合检索:BM25 + 向量召回 + 关键词命中加权 + RRF 融合

输出:
  - hits: 融合后的 top_k(沿用旧 schema)
  - trace: 各路径原始召回详情,便于 trace 日志
"""
import re
from typing import List, Dict, Any

from app.retrieval.embedder import embed_texts, vector_search, EMB_MODEL
from app.retrieval import bm25_index
from app.core.config import BM25_TOPK


def _keyword_score(text: str, query: str) -> float:
    if not text or not query:
        return 0.0
    terms = set()
    terms.add(query)
    for i in range(len(query) - 1):
        terms.add(query[i:i+2])
    if not terms:
        return 0.0
    text_lower = text
    hit = 0
    for t in terms:
        hit += len(re.findall(re.escape(t), text_lower))
    return min(hit / max(len(terms), 1), 5.0)


def hybrid_search(query: str, document_ids: List[int] = None, top_k: int = 5,
                  use_bm25: bool = True, use_vector: bool = True,
                  use_keyword: bool = True) -> Dict[str, Any]:
    """
    返回 dict:
      {
        "hits": [...],          # 融合后的 top_k(老 schema)
        "trace": {
          "bm25":    [{"chunk_id":..., "text":..., "score":...}, ...],
          "vector":  [{"chunk_id":..., "text":..., "score":...}, ...],
          "keyword_top": [{"chunk_id":..., "keyword_score":...}, ...],
          "candidates": [...],  # RRF 融合表
          "models": {"vector": "BAAI/bge-small-zh-v1.5"},
        }
      }
    """
    K = 60
    candidates: Dict[int, dict] = {}

    # ============== 1. BM25 ==============
    bm25_hits_raw: List[dict] = []
    if use_bm25:
        bm25_hits_raw = bm25_index.search(query, document_ids=document_ids, top_k=BM25_TOPK)
        for rank, it in enumerate(bm25_hits_raw, 1):
            cid = it["chunk_id"]
            if cid not in candidates:
                candidates[cid] = {
                    "chunk_id": cid,
                    "document_id": it.get("document_id"),
                    "version_id": it.get("version_id"),
                    "text": it.get("text", ""),
                    "page": it.get("page", ""),
                    "category": it.get("category", ""),
                    "doc_title": it.get("doc_title", ""),
                    "section_path": it.get("section_path", ""),
                    "image_id": it.get("image_id", ""),
                    "image_url": it.get("image_url", ""),
                    "rrf": 0.0,
                    "scores": {},
                }
            candidates[cid]["rrf"] += 1.0 / (K + rank)
            candidates[cid]["scores"]["bm25"] = it.get("score", 0.0)

    # ============== 2. 向量 ==============
    vec_hits_raw: List[dict] = []
    if use_vector:
        q_vec = embed_texts([query])[0].tolist()
        filter_expr = None
        if document_ids is not None:
            ids_str = ",".join(str(i) for i in document_ids)
            filter_expr = f"document_id in [{ids_str}]"
        vec_hits_raw = vector_search(q_vec, top_k=BM25_TOPK, filter_expr=filter_expr)
        for rank, it in enumerate(vec_hits_raw, 1):
            cid = it["chunk_id"]
            # pymilvus 返回 hit 是 {'id', 'distance', 'entity': {...}}
            ent = it.get("entity", it)
            if cid not in candidates:
                candidates[cid] = {
                    "chunk_id": cid,
                    "document_id": ent.get("document_id"),
                    "version_id": ent.get("version_id"),
                    "text": ent.get("text", ""),
                    "page": ent.get("page", ""),
                    "category": ent.get("category", ""),
                    "doc_title": ent.get("doc_title", ""),
                    "section_path": ent.get("section_path", ""),
                    "image_id": ent.get("image_id", ""),
                    "image_url": ent.get("image_url", ""),
                    "rrf": 0.0,
                    "scores": {},
                }
            candidates[cid]["rrf"] += 1.2 / (K + rank)  # 向量略加权
            # pymilvus 用 distance(IP),越大越相似
            candidates[cid]["scores"]["vector"] = it.get("distance", 0.0)

    # ============== 3. 关键词命中加权 ==============
    kw_hits: List[dict] = []
    if use_keyword and candidates:
        for cid, info in candidates.items():
            ks = _keyword_score(info["text"], query)
            info["scores"]["keyword"] = ks
            if ks > 0:
                info["rrf"] += 0.5 / (K + 1)
                kw_hits.append({"chunk_id": cid, "keyword_score": round(ks, 3)})

    # 排序
    ranked = sorted(candidates.values(), key=lambda x: -x["rrf"])

    # 输出 top_k
    out = []
    for r in ranked[:top_k]:
        out.append({
            "chunk_id": r["chunk_id"],
            "document_id": r["document_id"],
            "version_id": r["version_id"],
            "text": r["text"],
            "page": r["page"],
            "category": r["category"],
            "doc_title": r.get("doc_title", ""),
            "section_path": r.get("section_path", ""),
            "image_id": r.get("image_id", ""),
            "image_url": r.get("image_url", ""),
            "rrf_score": round(r["rrf"], 6),
            "scores": r["scores"],
        })

    return {
        "hits": out,
        "trace": {
            "bm25": [
                {"chunk_id": h.get("chunk_id"),
                 "score": round(h.get("score", 0.0), 4),
                 "text_preview": (h.get("text", "") or "")[:80]}
                for h in bm25_hits_raw
            ],
            "vector": [
                {"chunk_id": h.get("chunk_id"),
                 "distance": round(h.get("distance", 0.0), 4),
                 "text_preview": ((h.get("entity") or h).get("text", "") or "")[:80]}
                for h in vec_hits_raw
            ],
            "keyword": sorted(kw_hits, key=lambda x: -x["keyword_score"])[:10],
            "candidates": [
                {"chunk_id": c["chunk_id"],
                 "rrf": round(c["rrf"], 4),
                 "scores": {k: round(v, 4) for k, v in c["scores"].items()},
                 "doc_title": c.get("doc_title", "")}
                for c in ranked[:top_k]
            ],
            "models": {
                "vector": EMB_MODEL,
                "rerank": "RRF (reciprocal rank fusion, k=60)",
            },
        },
    }


def hybrid_search_simple(query: str, document_ids: List[int] = None,
                          top_k: int = 5, **kwargs) -> List[dict]:
    """旧接口兼容:只返回 hits 列表"""
    return hybrid_search(query, document_ids=document_ids, top_k=top_k, **kwargs)["hits"]
