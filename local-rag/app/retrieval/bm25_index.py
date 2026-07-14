"""BM25 索引:每个文档版本一个索引,常驻内存"""
import threading
import jieba
from rank_bm25 import BM25Okapi
from typing import List, Dict, Optional
from app.core.config import BM25_TOPK


_lock = threading.Lock()
# (document_id, version_id) -> {bm25, chunk_ids, texts}
_index_cache: Dict[tuple, dict] = {}


def _tokenize(text: str) -> List[str]:
    return [w for w in jieba.cut(text) if w.strip() and len(w) > 1]


def build_or_update(document_id: int, version_id: int, chunks: List[dict]):
    """chunks: [{'chunk_id': int, 'text': str}, ...]"""
    if not chunks:
        return
    corpus = [_tokenize(c["text"]) for c in chunks]
    # 过滤全 token 为空的文档(rank_bm25 会除零)
    corpus = [c if c else ["_empty_"] for c in corpus]
    bm25 = BM25Okapi(corpus)
    with _lock:
        _index_cache[(document_id, version_id)] = {
            "bm25": bm25,
            "chunk_ids": [c["chunk_id"] for c in chunks],
            "texts": [c["text"] for c in chunks],
        }


def remove(document_id: int, version_id: int = None):
    with _lock:
        if version_id is None:
            keys = [k for k in _index_cache if k[0] == document_id]
            for k in keys:
                _index_cache.pop(k, None)
        else:
            _index_cache.pop((document_id, version_id), None)


def search(query: str, document_ids: Optional[List[int]] = None,
           top_k: int = BM25_TOPK) -> List[dict]:
    """返回 [{'chunk_id', 'document_id', 'version_id', 'text', 'score', 'method': 'bm25'}]"""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    results = []
    with _lock:
        for (doc_id, ver_id), idx_data in _index_cache.items():
            if document_ids is not None and doc_id not in document_ids:
                continue
            scores = idx_data["bm25"].get_scores(q_tokens)
            top_idx = scores.argsort()[::-1][:top_k]
            for i in top_idx:
                if scores[i] <= 0:
                    continue
                results.append({
                    "chunk_id": idx_data["chunk_ids"][i],
                    "document_id": doc_id,
                    "version_id": ver_id,
                    "text": idx_data["texts"][i],
                    "score": float(scores[i]),
                    "method": "bm25",
                })
    results.sort(key=lambda x: -x["score"])
    return results[:top_k]


def has_index(document_id: int, version_id: int) -> bool:
    with _lock:
        return (document_id, version_id) in _index_cache


def total_indexes() -> int:
    with _lock:
        return len(_index_cache)