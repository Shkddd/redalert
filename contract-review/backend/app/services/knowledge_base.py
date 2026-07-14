"""Knowledge base service — CRUD and hybrid search against vector + BM25 indexes."""
import json
import re
from typing import Optional, List, Dict
from .db import get_db
from ..config import get_settings
from .kb_vector import (
    hybrid_search as vector_hybrid_search,
    import_file as vec_import_file,
    import_url as vec_import_url,
    list_sources as vec_list_sources,
    delete_source as vec_delete_source,
    get_chunks as vec_get_chunks,
)


# ── Legacy KB CRUD (knowledge_base table) ──

def list_entries(category: Optional[str] = None, search: Optional[str] = None) -> List[dict]:
    """List knowledge base entries, optionally filtered."""
    db = get_db()
    params = []
    sql = "SELECT * FROM knowledge_base WHERE 1=1"

    if category:
        sql += " AND category = ?"
        params.append(category)
    if search:
        sql += " AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])

    sql += " ORDER BY risk_level DESC, id ASC"
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_entry(entry_id: int) -> Optional[dict]:
    db = get_db()
    r = db.execute("SELECT * FROM knowledge_base WHERE id = ?", (entry_id,)).fetchone()
    return dict(r) if r else None


def create_entry(title: str, category: str, content: str, risk_level: str = "中", tags: str = "") -> dict:
    db = get_db()
    cur = db.execute(
        "INSERT INTO knowledge_base (title, category, content, risk_level, tags) VALUES (?, ?, ?, ?, ?)",
        (title, category, content, risk_level, tags),
    )
    db.commit()
    return get_entry(cur.lastrowid)


def update_entry(entry_id: int, **kwargs) -> Optional[dict]:
    db = get_db()
    fields = {k: v for k, v in kwargs.items() if v is not None}
    if not fields:
        return get_entry(entry_id)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    set_clause = set_clause.replace("updated_at = ?", "updated_at = datetime('now', 'localtime')")
    vals = [v for k, v in fields.items() if k != "updated_at"]
    vals.append(entry_id)
    db.execute(f"UPDATE knowledge_base SET {set_clause} WHERE id = ?", vals)
    db.commit()
    return get_entry(entry_id)


def delete_entry(entry_id: int) -> bool:
    db = get_db()
    db.execute("DELETE FROM knowledge_base WHERE id = ?", (entry_id,))
    db.commit()
    return db.total_changes > 0


def list_categories() -> List[str]:
    db = get_db()
    rows = db.execute("SELECT DISTINCT category FROM knowledge_base ORDER BY category").fetchall()
    return [r["category"] for r in rows]


# ── Hybrid search (vector + BM25 across kb_chunks + legacy KB) ──

def hybrid_search(query: str, top_k: int = 5) -> List[dict]:
    """Hybrid search across both vector/BMI25 chunks and legacy KB entries.

    Returns a combined, deduplicated list sorted by relevance.
    """
    chunks = vector_hybrid_search(query, top_k=top_k)

    # Also search legacy knowledge_base table
    legacy = _legacy_search(query, top_k=top_k)

    # Merge: prefer chunks, fill remaining slots with legacy entries
    seen_ids = {c["id"] for c in chunks}
    for e in legacy:
        if len(chunks) >= top_k:
            break
        legacy_key = f"kb_{e['id']}"
        if legacy_key not in seen_ids:
            e["id"] = legacy_key
            e["source_type"] = "legacy_kb"
            e["score"] = e.pop("relevance", 50) / 100.0
            chunks.append(e)

    return chunks[:top_k]


def _legacy_search(query: str, top_k: int = 5) -> List[dict]:
    """Search the legacy knowledge_base table with keyword + simple relevance."""
    db = get_db()
    words = [w for w in re.split(r"[，。、；：\s,.;: ]", query) if len(w) >= 2]
    if not words:
        return []

    like_clauses = " OR ".join(["(title LIKE ? OR content LIKE ? OR tags LIKE ?)" for _ in words])
    params = []
    for w in words:
        like = f"%{w}%"
        params.extend([like, like, like])

    rows = db.execute(
        f"SELECT *, 1 as relevance "
        f"FROM knowledge_base WHERE {like_clauses} "
        f"ORDER BY risk_level DESC, id ASC LIMIT ?",
        params + [top_k],
    ).fetchall()
    return [dict(r) for r in rows]


# ── Vector store operations (forwarded from kb_vector) ──

def import_file(file_path: str) -> Optional[int]:
    """Import a PDF/DOCX file into the vector KB."""
    return vec_import_file(file_path)


def import_url(url: str) -> Optional[int]:
    """Fetch text from URL and import into the vector KB."""
    return vec_import_url(url)


def list_sources() -> List[dict]:
    """List imported KB sources."""
    return vec_list_sources()


def delete_source(source_id: int) -> bool:
    """Delete an imported KB source and its chunks."""
    return vec_delete_source(source_id)


def get_chunks(source_id: int = None, query: str = None, top_k: int = 20) -> List[dict]:
    """List or search chunks."""
    return vec_get_chunks(source_id, query, top_k)
