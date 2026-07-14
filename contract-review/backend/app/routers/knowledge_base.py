"""Knowledge base API routes — legacy CRUD + vector store import + hybrid search."""
import json
import os
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from ..services import knowledge_base as kb
from ..models.schemas import KBEntryCreate, KBEntryResponse, KBEntryUpdate

router = APIRouter(prefix="/api/kb", tags=["knowledge_base"])


# ── Legacy knowledge_base CRUD ──

@router.get("/entries")
def list_entries(category: str = None, search: str = None):
    return kb.list_entries(category, search)


@router.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    e = kb.get_entry(entry_id)
    if not e:
        raise HTTPException(404, "Entry not found")
    return e


@router.post("/entries", response_model=KBEntryResponse)
def create_entry(data: KBEntryCreate):
    return kb.create_entry(data.title, data.category, data.content, data.risk_level, data.tags)


@router.put("/entries/{entry_id}", response_model=KBEntryResponse)
def update_entry(entry_id: int, data: KBEntryUpdate):
    e = kb.update_entry(entry_id, **data.model_dump(exclude_unset=True))
    if not e:
        raise HTTPException(404, "Entry not found")
    return e


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int):
    if not kb.delete_entry(entry_id):
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


@router.get("/categories")
def list_categories():
    return kb.list_categories()


# ── Vector KB: document / URL import ──

@router.post("/import-file")
async def import_file(file: UploadFile = File(...)):
    """Upload a PDF/DOCX file and import into the vector knowledge base."""
    from ..config import get_settings
    settings = get_settings()

    # Save uploaded file
    upload_dir = settings.upload_dir / "kb_import"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)

    # Import into KB
    source_id = kb.import_file(str(dest))
    if source_id is None:
        raise HTTPException(400, "Unsupported file type or empty content")
    return {"ok": True, "source_id": source_id, "source_name": file.filename}


@router.post("/import-url")
def import_url(url: str = Form(...)):
    """Import a URL's text content into the vector knowledge base."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Invalid URL")
    source_id = kb.import_url(url)
    if source_id is None:
        raise HTTPException(400, "Failed to fetch or parse URL content")
    return {"ok": True, "source_id": source_id}


# ── Vector KB: source / chunk management ──

@router.get("/sources")
def list_sources():
    return kb.list_sources()


@router.delete("/sources/{source_id}")
def delete_source(source_id: int):
    if not kb.delete_source(source_id):
        raise HTTPException(404, "Source not found")
    return {"ok": True}


@router.get("/chunks")
def get_chunks(source_id: int = None, query: str = None, top_k: int = 20):
    return kb.get_chunks(source_id, query, top_k)


# ── Search ──

@router.get("/hybrid-search")
def hybrid_search(query: str, top_k: int = 5):
    """Hybrid search across vector store + BM25 + legacy KB entries."""
    return kb.hybrid_search(query, top_k)
