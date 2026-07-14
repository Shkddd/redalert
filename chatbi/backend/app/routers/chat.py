"""ChatBI API routes — natural language queries, schema info, health."""

from __future__ import annotations
import uuid
import time
import aiosqlite
from fastapi import APIRouter, HTTPException, UploadFile, File
from ..models.schemas import (
    ChatRequest, ChatResponse, SchemaInfo, HealthResponse,
    UploadResponse, UploadInfo, UploadListResponse, DeleteUploadResponse,
)
from ..services.data_context import get_db_schema, get_metric_recommendations, build_extended_schema_description
from ..services.nl_to_sql import generate_sql
from ..services.query_executor import execute_query, build_chart_data
from ..services.excel_import import import_excel, list_uploads, delete_upload
from ..config import get_settings

router = APIRouter()

# In-memory conversation history (per conversation_id)
_conversations: dict[str, list[dict]] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main ChatBI endpoint — natural language in, data + visualization out."""
    start = time.time()
    conv_id = request.conversation_id or "default"

    if conv_id not in _conversations:
        _conversations[conv_id] = []
    history = _conversations[conv_id]

    settings = get_settings()
    db_path = settings.db_path

    # Build dynamic schema including any uploaded tables
    schema_text = await build_extended_schema_description(db_path)

    # Step 1: NL → SQL via LLM
    llm_result = generate_sql(
        question=request.message,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        conversation_history=history,
        schema_text=schema_text,
    )

    sql = llm_result.get("sql", "")
    explanation = llm_result.get("explanation", "")
    visualization = llm_result.get("visualization")

    if not sql:
        resp = ChatResponse(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            answer=explanation,
            error="llm_failed",
        )

        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": explanation})
        if len(history) > 20:
            history[:] = history[-20:]

        return resp

    # Step 2: Execute SQL (async)
    query_result = await execute_query(db_path, sql)

    if query_result.get("error"):
        answer = f"SQL执行出错：{query_result['error']}\n\n生成的SQL：\n```sql\n{sql}\n```"
        if explanation:
            answer = f"{explanation}\n\n但执行时出错：{query_result['error']}\n\nSQL：\n```sql\n{sql}\n```"

        resp = ChatResponse(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            answer=answer,
            sql=sql,
            error=query_result["error"],
            execution_time_ms=(time.time() - start) * 1000,
        )

        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": answer})
        return resp

    # Step 3: Build chart data
    chart_data = build_chart_data(
        query_result["data"],
        query_result["columns"],
        visualization,
    )

    data_summary = _format_data_answer(query_result["data"], query_result["columns"], explanation, sql)

    total_time = (time.time() - start) * 1000

    resp = ChatResponse(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        answer=data_summary,
        sql=sql,
        data=query_result["data"],
        columns=query_result["columns"],
        chart_type=chart_data["type"] if chart_data else None,
        chart_data=chart_data,
        execution_time_ms=round(total_time, 1),
    )

    history.append({"role": "user", "content": request.message})
    history.append({"role": "assistant", "content": resp.model_dump_json()})
    if len(history) > 20:
        history[:] = history[-20:]

    return resp


@router.get("/schema", response_model=SchemaInfo)
async def get_schema():
    """Return database schema for reference."""
    settings = get_settings()
    tables = await get_db_schema(settings.db_path)
    return SchemaInfo(tables=tables)


@router.get("/metrics")
async def get_metrics():
    """Return suggested metrics/questions."""
    return get_metric_recommendations()


@router.get("/history/{conversation_id}")
async def get_history(conversation_id: str):
    """Get conversation history."""
    history = _conversations.get(conversation_id, [])
    return {"conversation_id": conversation_id, "messages": history}


@router.delete("/history/{conversation_id}")
async def clear_history(conversation_id: str):
    """Clear conversation history."""
    if conversation_id in _conversations:
        del _conversations[conversation_id]
    return {"status": "cleared"}


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    settings = get_settings()
    db_path = settings.db_path
    import os

    try:
        conn = await aiosqlite.connect(db_path)
        row = await (await conn.execute("SELECT COUNT(*) FROM orders")).fetchone()
        count = row[0] if row else 0
        await conn.close()
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        seed_loaded = count > 0
    except Exception:
        count = 0
        db_size = 0
        seed_loaded = False

    return HealthResponse(
        status="ok",
        llm_configured=bool(settings.llm_api_key),
        db_size=db_size,
        seed_data_loaded=seed_loaded,
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_excel(file: UploadFile = File(...)):
    """Upload an Excel file to create a new database table."""
    settings = get_settings()

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 格式的Excel文件")

    file_bytes = await file.read()
    max_size = 10 * 1024 * 1024
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=400, detail="文件大小超过10MB限制")

    try:
        result = await import_excel(settings.db_path, file_bytes, file.filename)
        return UploadResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/uploads", response_model=UploadListResponse)
async def get_uploads():
    """List all uploaded Excel tables."""
    settings = get_settings()
    uploads = await list_uploads(settings.db_path)
    return UploadListResponse(uploads=uploads)


@router.delete("/uploads/{table_name}", response_model=DeleteUploadResponse)
async def remove_upload(table_name: str):
    """Delete an uploaded table and its tracking record."""
    settings = get_settings()
    try:
        await delete_upload(settings.db_path, table_name)
        return DeleteUploadResponse(status="deleted", table_name=table_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _format_data_answer(
    data: list[dict],
    columns: list[str],
    explanation: str,
    sql: str,
) -> str:
    """Format query results into a readable answer."""
    if not data:
        return f"{explanation}\n\n查询结果为空。"

    n = len(data)
    lines = [explanation, ""]
    if n <= 20:
        if len(columns) >= 2:
            for row in data[:10]:
                vals = [str(row[c]) for c in columns[:3]]
                lines.append("  \u2022 " + " | ".join(vals))
            if n > 10:
                lines.append(f"  ... 还有 {n - 10} 条")
    lines.append(f"\n共 {n} 条结果  |  查看下方表格和图表")

    return "\n".join(lines)
