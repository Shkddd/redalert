"""Document upload and listing endpoints."""

import os
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from ..services.db import get_db
from ..services.document_parser import get_file_type, parse_and_store
from ..models.schemas import UploadResponse, DocumentResponse

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF or DOCX contract document."""
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {ext}，仅支持 PDF、DOCX")

    # Save file
    from ..config import get_settings
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = settings.upload_dir / unique_name

    content = await file.read()
    filepath.write_bytes(content)

    # Create DB record
    db = get_db()
    cur = db.execute(
        "INSERT INTO documents (filename, original_name, file_type, file_path, status) VALUES (?, ?, ?, ?, 'parsing')",
        (unique_name, file.filename, ext.lstrip("."), str(filepath)),
    )
    doc_id = cur.lastrowid
    db.commit()

    # Parse document (async in background)
    try:
        clause_count = parse_and_store(str(filepath), doc_id)
    except Exception as e:
        cur2 = db.execute("UPDATE documents SET status = 'error' WHERE id = ?", (doc_id,))
        db.commit()
        raise HTTPException(500, f"文档解析失败: {str(e)}")

    return UploadResponse(
        id=doc_id,
        filename=unique_name,
        original_name=file.filename,
        file_type=ext.lstrip("."),
        message=f"上传成功，解析出 {clause_count} 个条款",
    )


@router.get("", response_model=list[DocumentResponse])
def list_documents():
    """List all uploaded documents."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM documents ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(doc_id: int):
    """Get document details."""
    db = get_db()
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(404, "文档不存在")
    return dict(row)


@router.get("/{doc_id}/clauses")
def get_clauses(doc_id: int):
    """Get all clauses for a document."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM clauses WHERE doc_id = ? ORDER BY clause_index", (doc_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/{doc_id}")
def delete_document(doc_id: int):
    """Delete a document and its associated files."""
    db = get_db()
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(404, "文档不存在")

    # Delete file
    filepath = Path(row["file_path"])
    if filepath.exists():
        filepath.unlink()

    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    db.commit()
    return {"message": "已删除"}
