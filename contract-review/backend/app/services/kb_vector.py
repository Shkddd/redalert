"""Knowledge base vector service — chunking, embeddings, hybrid search (vector + BM25).

Supports:
- Import documents from files (PDF/DOCX) and URLs
- Text chunking with overlap
- Embedding via provider API (OpenAI-compatible /embeddings)
- Fallback embedding via TF-IDF (no external API needed)
- FTS4 BM25 keyword search
- Cosine similarity vector search
- Hybrid search (RRF fusion of vector + BM25 scores)
"""

import json
import re
import math
import struct
from io import BytesIO
from typing import Optional, List, Dict, Union
from collections import Counter

import numpy as np
import httpx
from ..config import get_settings
from .db import get_db


# ── Constants ──

CHUNK_SIZE = 300       # characters per chunk
CHUNK_OVERLAP = 60     # overlap between chunks
EMBED_DIM = 384        # fallback TF-IDF embedding dimension (truncated SVD)
EMBED_MODELS = [       # model names to try, in order
    "text-embedding-ada-002",
    "text-embedding-v2",
    "deepseek-embedding",
    "bge-large-zh",
    "text-embedding-3-small",
]
HYBRID_WEIGHT_VECTOR = 0.6   # weight for vector similarity score
HYBRID_WEIGHT_BM25 = 0.4     # weight for BM25 keyword score
RRF_K = 60                   # RRF constant


# ═══════════════════════════════════════════════
# 1. Text Chunking
# ═══════════════════════════════════════════════

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks at sentence/paragraph boundaries."""
    if not text or not text.strip():
        return []

    # Normalise whitespace
    text = re.sub(r"\s+", " ", text.strip())

    # Try to split on paragraph breaks first
    paragraphs = re.split(r"\n\s*\n", text)
    if len(paragraphs) < 2:
        # No paragraph breaks — split on sentence boundaries
        paragraphs = re.split(r"(?<=[。！？.!?])\s*", text)

    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) < size:
            current = (current + " " + para).strip()
        else:
            if current:
                chunks.append(current)
            # If para alone is huge, sub-split it
            while len(para) > size:
                # Find last sentence boundary within size limit
                cut = para.rfind("。", 0, size)
                if cut < size // 2:
                    cut = para.rfind(".", 0, size)
                if cut < size // 2:
                    cut = para.rfind("；", 0, size)
                if cut < size // 2:
                    cut = size
                else:
                    cut += 1
                chunks.append(para[:cut].strip())
                para = para[cut:].strip()
            current = para

    if current:
        chunks.append(current)

    # Apply overlap: merge overlapping suffixes from previous chunk
    if overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = merged[-1]
            overlap_text = prev[-overlap:] if len(prev) > overlap else prev
            merged.append((overlap_text + " " + chunks[i]).strip())
        chunks = merged

    return chunks


# ═══════════════════════════════════════════════
# 2. Embedding
# ═══════════════════════════════════════════════

_embedded_model_used: Optional[str] = None
_embedding_fallback: bool = False


def get_embedding(text: str) -> Optional[np.ndarray]:
    """Get embedding vector via provider API, or fallback to TF-IDF.

    Returns a numpy float32 array of EMBED_DIM or None on failure.
    """
    global _embedded_model_used, _embedding_fallback

    if _embedding_fallback:
        return None

    settings = get_settings()
    if not settings.llm_api_key:
        _embedding_fallback = True
        return None

    models_to_try = EMBED_MODELS

    if _embedded_model_used:
        # Previously succeeded with a specific model — use it directly
        models_to_try = [_embedded_model_used, *EMBED_MODELS]

    last_err = None
    for model in models_to_try:
        if model == _embedded_model_used:
            # Already tried and failed — skip
            continue
        try:
            resp = httpx.post(
                f"{settings.llm_base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": text[:8192],  # Truncate to avoid token limits
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                vec = data["data"][0]["embedding"]
                _embedded_model_used = model
                return np.array(vec, dtype=np.float32)
            last_err = f"{model}: HTTP {resp.status_code}"
        except Exception as e:
            last_err = f"{model}: {e}"

    _embedding_fallback = True
    return None


def _build_tfidf_vectors(texts: List[str], dim: int = EMBED_DIM) -> np.ndarray:
    """Build TF-IDF vectors from a corpus of texts using numpy.

    Returns (N, dim) float32 array, each row normalised to unit length.
    """
    if not texts:
        return np.zeros((0, dim), dtype=np.float32)

    # Tokenise Chinese text by character bigrams + English words
    def tokenise(s: str) -> List[str]:
        s = s.lower()
        tokens = []
        # Chinese character bigrams
        chars = re.findall(r"[\u4e00-\u9fff]", s)
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i + 1])
        # English words
        for w in re.findall(r"[a-z]+", s):
            if len(w) >= 2:
                tokens.append(w)
        return tokens

    # Build vocabulary from all texts
    all_tokens = [tokenise(t) for t in texts]
    vocab: Dict[str, int] = {}
    for tokens in all_tokens:
        for t in tokens:
            if t not in vocab:
                vocab[t] = len(vocab)

    if not vocab:
        return np.zeros((len(texts), dim), dtype=np.float32)

    # Compute IDF
    n_docs = len(texts)
    idf: Dict[str, float] = {}
    for t in vocab:
        df = sum(1 for tokens in all_tokens if t in tokens)
        idf[t] = math.log((n_docs + 1) / (df + 1)) + 1

    # Build TF-IDF vectors
    vecs = np.zeros((len(texts), len(vocab)), dtype=np.float32)
    for i, tokens in enumerate(all_tokens):
        tf = Counter(tokens)
        for t, cnt in tf.items():
            if t in vocab:
                vecs[i, vocab[t]] = cnt * idf[t]

    # L2 normalise
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vecs = vecs / norms

    # If dim < vocab size, truncate (simple SVD approximation)
    if dim < vecs.shape[1]:
        # Take first dim columns (coarse approximation)
        vecs = vecs[:, :dim]
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vecs = vecs / norms
    elif dim > vecs.shape[1]:
        # Pad with zeros
        padded = np.zeros((len(texts), dim), dtype=np.float32)
        padded[:, :vecs.shape[1]] = vecs
        vecs = padded

    return vecs


# ═══════════════════════════════════════════════
# 3. Serialisation helpers
# ═══════════════════════════════════════════════

def _serialise_embedding(vec: Optional[np.ndarray]) -> Optional[bytes]:
    """Serialise numpy float32 array to bytes for SQLite BLOB storage."""
    if vec is None:
        return None
    buf = BytesIO()
    np.save(buf, vec.astype(np.float32))
    return buf.getvalue()


def _deserialise_embedding(blob: Optional[bytes]) -> Optional[np.ndarray]:
    """Deserialise numpy float32 array from SQLite BLOB."""
    if blob is None:
        return None
    buf = BytesIO(blob)
    return np.load(buf).astype(np.float32)


# ═══════════════════════════════════════════════
# 4. Store & Import
# ═══════════════════════════════════════════════

def store_chunks(source_id: int, chunks: List[str],
                 embeddings: Optional[List[Optional[np.ndarray]]] = None) -> int:
    """Store chunks and their embeddings for a source.

    Returns number of chunks stored.
    """
    db = get_db()
    db.execute("DELETE FROM kb_chunks WHERE source_id = ?", (source_id,))

    for i, chunk in enumerate(chunks):
        emb = _serialise_embedding(embeddings[i] if embeddings else None)
        db.execute(
            "INSERT INTO kb_chunks (source_id, chunk_index, content, embedding) VALUES (?, ?, ?, ?)",
            (source_id, i, chunk, emb),
        )

    db.execute("UPDATE kb_sources SET chunk_count = ? WHERE id = ?",
               (len(chunks), source_id))
    db.commit()
    return len(chunks)


def create_source(source_type: str, source_name: str,
                  source_url: str = "") -> int:
    """Create a new source and return its ID."""
    db = get_db()
    cur = db.execute(
        "INSERT INTO kb_sources (source_type, source_name, source_url) VALUES (?, ?, ?)",
        (source_type, source_name, source_url),
    )
    db.commit()
    return cur.lastrowid


def import_text(source_id: int, text: str) -> int:
    """Chunk text, compute embeddings, store everything.

    Returns chunk count.
    """
    chunks = chunk_text(text)
    if not chunks:
        return 0

    # Compute embeddings in batches
    embeddings: List[Optional[np.ndarray]] = [None] * len(chunks)
    all_none = True
    for i, chunk in enumerate(chunks):
        vec = get_embedding(chunk)
        if vec is not None:
            embeddings[i] = vec
            all_none = False

    if all_none:
        # Fallback: compute TF-IDF vectors for all chunks
        vecs = _build_tfidf_vectors(chunks)
        for i in range(len(chunks)):
            embeddings[i] = vecs[i]

    return store_chunks(source_id, chunks, embeddings)


def import_file(file_path: str) -> Optional[int]:
    """Import a PDF/DOCX file into KB. Returns source_id or None."""
    from .document_parser import parse_document

    path_lower = file_path.lower()
    if not (path_lower.endswith(".pdf") or path_lower.endswith(".docx")):
        return None

    text = parse_document(file_path)
    if not text or not text.strip():
        return None

    source_name = file_path.rsplit("/", 1)[-1]
    source_id = create_source("file", source_name, file_path)
    count = import_text(source_id, text)
    return source_id if count > 0 else None


def import_url(url: str) -> Optional[int]:
    """Fetch text from a URL and import into KB. Returns source_id or None."""
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        return None

    html = resp.text
    text = _extract_text_from_html(html)
    if not text or not text.strip():
        # Fallback: just take everything
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

    source_name = url.rstrip("/").rsplit("/", 1)[-1] or url[:50]
    source_id = create_source("url", source_name, url)
    count = import_text(source_id, text)
    return source_id if count > 0 else None


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML using simple heuristics (no deps)."""
    # Strip script/style tags
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove comments
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    # Extract text from common content tags
    texts = []
    for tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "blockquote"):
        for m in re.finditer(f"<{tag}[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE):
            t = re.sub(r"<[^>]+>", " ", m.group(1))
            t = re.sub(r"&[a-z]+;", " ", t)
            t = re.sub(r"\s+", " ", t).strip()
            if len(t) >= 10:
                texts.append(t)

    result = "\n".join(texts)
    return result


# ═══════════════════════════════════════════════
# 5. Search
# ═══════════════════════════════════════════════

def bm25_search(query: str, top_k: int = 5) -> List[dict]:
    """Search chunks using pure Python BM25 scoring. Returns [{id, content, source_id, score}, ...]."""
    db = get_db()

    # Load all chunks
    rows = db.execute(
        "SELECT id, content, source_id, metadata FROM kb_chunks"
    ).fetchall()
    if not rows:
        return []
    docs = [dict(r) for r in rows]

    # Tokenize
    def tokenize(text: str) -> List[str]:
        # Simple tokenizer: split on whitespace/punctuation, keep CJK chars
        tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower())
        return [t for t in tokens if len(t) >= 1]

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    doc_tokens = [tokenize(d["content"]) for d in docs]
    N = len(docs)

    # k1 and b are standard BM25 parameters
    k1, b = 1.2, 0.75

    # Average document length
    avg_len = sum(len(t) for t in doc_tokens) / max(N, 1)

    # Precompute IDF for each query term
    idf_cache = {}
    for term in set(query_tokens):
        n = sum(1 for t in doc_tokens if term in t)
        idf_cache[term] = math.log((N - n + 0.5) / (max(n, 1) + 0.5) + 1.0)

    # Score each document
    results = []
    for i, doc in enumerate(docs):
        tokens = doc_tokens[i]
        doc_len = len(tokens)
        score = 0.0
        for term in query_tokens:
            tf = tokens.count(term)
            if tf == 0:
                continue
            idf = idf_cache.get(term, 1.0)
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_len))

        if score > 0:
            doc["score"] = round(score, 4)
            results.append(doc)

    # Sort by score descending, return top_k
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def vector_search(query_embedding: np.ndarray, top_k: int = 5,
                  source_ids: Optional[List[int]] = None) -> List[dict]:
    """Search chunks by cosine similarity against all stored embeddings.

    Uses numpy for fast dot product (all embeddings loaded at query time).
    Best suited for KBs up to ~50,000 chunks.
    """
    db = get_db()
    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        rows = db.execute(
            f"SELECT id, content, source_id, metadata, embedding FROM kb_chunks "
            f"WHERE embedding IS NOT NULL AND source_id IN ({placeholders})",
            source_ids,
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, content, source_id, metadata, embedding FROM kb_chunks "
            "WHERE embedding IS NOT NULL"
        ).fetchall()

    if not rows:
        return []

    ids = []
    chunks = []
    emb_list = []
    for r in rows:
        emb = _deserialise_embedding(r["embedding"])
        if emb is not None and emb.shape[0] > 0:
            ids.append(r["id"])
            chunks.append(dict(r))
            emb_list.append(emb)

    if not emb_list:
        return []

    # Stack into (N, D) matrix
    mat = np.stack(emb_list, axis=0).astype(np.float32)

    # Cosine similarity
    q = query_embedding.astype(np.float32).reshape(1, -1)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q = q / q_norm

    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1
    mat = mat / norms

    scores = (mat @ q.T).flatten()

    # Top-K
    top_indices = np.argsort(scores)[-top_k:][::-1]
    results = []
    for idx in top_indices:
        if scores[idx] > 0.05:
            chunk = dict(chunks[idx])
            chunk["score"] = float(scores[idx])
            results.append(chunk)

    return results


def hybrid_search(query: str, top_k: int = 5,
                  source_ids: Optional[List[int]] = None) -> List[dict]:
    """Hybrid search combining vector similarity + BM25 using RRF fusion.

    1. Gets vector search results (if embeddings available)
    2. Gets BM25 results from FTS4
    3. Fuses scores using Reciprocal Rank Fusion (RRF)
    """
    # Step 1: get query embedding
    query_embedding = get_embedding(query)
    has_vector = query_embedding is not None

    # Step 2: get results from both methods
    vector_results: List[dict] = []
    bm25_results: List[dict] = []

    if has_vector:
        vector_results = vector_search(query_embedding, top_k * 2, source_ids)

    bm25_results = bm25_search(query, top_k * 2)

    # Step 3: If only one method returned results, just use those
    if not vector_results and not bm25_results:
        return []

    if not vector_results:
        return _apply_rrf(bm25_results, None)
    if not bm25_results:
        return _apply_rrf(vector_results, None)

    # Step 4: RRF fusion
    return _apply_rrf(vector_results, bm25_results, top_k)


def _apply_rrf(vector_results: Optional[List[dict]],
               bm25_results: Optional[List[dict]],
               top_k: int = 5) -> List[dict]:
    """Apply Reciprocal Rank Fusion to combine two ranked result lists."""

    scores: dict[int, dict] = {}

    if vector_results:
        for rank, r in enumerate(vector_results):
            cid = r["id"]
            if cid not in scores:
                scores[cid] = {"id": cid, "content": r["content"],
                               "source_id": r["source_id"], "metadata": r.get("metadata", "{}"),
                               "vector_score": 0.0, "bm25_score": 0.0}
            scores[cid]["vector_score"] = 1.0 / (RRF_K + rank + 1)

    if bm25_results:
        for rank, r in enumerate(bm25_results):
            cid = r["id"]
            if cid not in scores:
                scores[cid] = {"id": cid, "content": r["content"],
                               "source_id": r["source_id"], "metadata": r.get("metadata", "{}"),
                               "vector_score": 0.0, "bm25_score": 0.0}
            scores[cid]["bm25_score"] = 1.0 / (RRF_K + rank + 1)

    # Compute final RRF score
    for cid in scores:
        v = scores[cid]["vector_score"]
        b = scores[cid]["bm25_score"]
        scores[cid]["score"] = round((v * HYBRID_WEIGHT_VECTOR + b * HYBRID_WEIGHT_BM25), 4)

    # Sort by score descending
    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]


# ═══════════════════════════════════════════════
# 6. Source management
# ═══════════════════════════════════════════════

def list_sources() -> List[dict]:
    """List all imported KB sources."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM kb_sources ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_source(source_id: int) -> bool:
    """Delete source and all its chunks (cascaded via FK + FTS triggers)."""
    db = get_db()
    db.execute("DELETE FROM kb_sources WHERE id = ?", (source_id,))
    db.commit()
    return db.total_changes > 0


def get_chunks(source_id: int = None, query: str = None, top_k: int = 20) -> List[dict]:
    """List chunks, optionally filtered by source or search query."""
    db = get_db()
    if query:
        return hybrid_search(query, top_k)

    if source_id:
        rows = db.execute(
            "SELECT * FROM kb_chunks WHERE source_id = ? ORDER BY chunk_index LIMIT ?",
            (source_id, top_k),
        )
    else:
        rows = db.execute(
            "SELECT * FROM kb_chunks ORDER BY source_id, chunk_index LIMIT ?",
            (top_k,),
        )
    return [dict(r) for r in rows.fetchall()]
