"""Pydantic schemas for ChatBI API."""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional


class ChatRequest(BaseModel):
    message: str = Field(..., description="Natural language question", max_length=2000)
    conversation_id: Optional[str] = Field(None, description="Keep conversation context", max_length=100)


class ChatResponse(BaseModel):
    id: str = Field(..., description="Response ID")
    conversation_id: str = Field("default", description="Conversation ID")
    answer: str = Field(..., description="Natural language answer")
    sql: Optional[str] = Field(None, description="Generated SQL")
    data: Optional[list[dict[str, Any]]] = Field(None, description="Query results")
    columns: Optional[list[str]] = Field(None, description="Column names")
    chart_type: Optional[str] = Field(None, description="Suggested chart type")
    chart_data: Optional[dict[str, Any]] = Field(None, description="Chart-friendly data")
    error: Optional[str] = Field(None, description="Error message if any")
    execution_time_ms: Optional[float] = Field(None, description="Total time")


class SchemaInfo(BaseModel):
    """Database schema exposed to the frontend for reference."""
    tables: list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: str = "ok"
    llm_configured: bool = False
    db_size: int = 0
    seed_data_loaded: bool = False


class UploadResponse(BaseModel):
    table_name: str
    original_filename: str
    display_name: str
    row_count: int
    column_count: int
    created_at: str


class UploadInfo(BaseModel):
    id: int
    original_filename: str
    table_name: str
    display_name: str
    created_at: str
    row_count: int
    column_count: int


class UploadListResponse(BaseModel):
    uploads: list[UploadInfo]


class DeleteUploadResponse(BaseModel):
    status: str
    table_name: str
