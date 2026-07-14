"""Contract review endpoints — run review and get results."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from ..services.db import get_db
from ..services.annotator import run_review, get_review_result
from ..services.annotated_export import export_annotated

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/{doc_id}")
def get_review(doc_id: int):
    """Get existing review result for a document."""
    result = get_review_result(doc_id)
    if result.get("status") == "pending":
        db = get_db()
        doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(404, "文档不存在")
        return {"status": "pending", "doc_id": doc_id, "doc_name": doc["original_name"]}
    return result


@router.post("/{doc_id}")
def start_review(doc_id: int):
    """Start (or restart) a review for a document."""
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc["status"] == "parsing":
        raise HTTPException(400, "文档正在解析中，请稍后")

    try:
        result = run_review(doc_id)
        return {"message": "审核完成", "result": result}
    except Exception as e:
        raise HTTPException(500, f"审核失败: {str(e)}")


@router.get("/history/all")
def get_all_reviews():
    """Get all reviews across documents."""
    db = get_db()
    rows = db.execute("""
        SELECT r.*, d.original_name as doc_name
        FROM reviews r
        JOIN documents d ON r.doc_id = d.id
        ORDER BY r.created_at DESC
        LIMIT 50
    """).fetchall()
    return [dict(r) for r in rows]


@router.get("/{doc_id}/annotated")
def download_annotated(doc_id: int):
    """Download AI-annotated version of the reviewed contract."""
    result = export_annotated(doc_id, "/tmp/contract_annotations")
    if "error" in result:
        raise HTTPException(400, result["error"])
    import urllib.parse
    safe_name = urllib.parse.quote(result["filename"])
    return FileResponse(
        path=result["filepath"],
        media_type=result["mime"],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}",
        },
    )
