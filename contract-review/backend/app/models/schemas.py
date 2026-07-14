"""Pydantic models for ContractReview API."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Knowledge Base ──

class KBEntryCreate(BaseModel):
    title: str = Field(..., description="标准条款标题")
    category: str = Field(default="通用", description="分类：通用/劳动法/采购/保密/知识产权等")
    content: str = Field(..., description="标准条款全文")
    risk_level: str = Field(default="中", description="风险等级：高/中/低")
    tags: str = Field(default="", description="逗号分隔的标签")


class KBEntryUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    risk_level: Optional[str] = None
    tags: Optional[str] = None


class KBEntryResponse(BaseModel):
    id: int
    title: str
    category: str
    content: str
    risk_level: str
    tags: str
    created_at: str
    updated_at: str


# ── Documents ──

class DocumentResponse(BaseModel):
    id: int
    filename: str
    original_name: str
    file_type: str
    page_count: int
    status: str  # uploaded / parsing / parsed / error
    clause_count: int
    created_at: str


class ClauseResponse(BaseModel):
    id: int
    doc_id: int
    clause_index: int
    content: str
    page_number: int
    section_title: str


# ── Review / Annotations ──

class AnnotationResponse(BaseModel):
    id: int
    clause_id: int
    kb_entry_id: Optional[int]
    kb_title: str
    match_type: str  # match / conflict / missing
    risk_level: str
    comment: str
    suggestion: str


class ReviewResultResponse(BaseModel):
    doc_id: int
    doc_name: str
    total_clauses: int
    matched: int
    conflicted: int
    missing: int
    high_risk: int
    medium_risk: int
    low_risk: int
    annotations: list[dict]
    created_at: str


# ── Upload Response ──

class UploadResponse(BaseModel):
    id: int
    filename: str
    original_name: str
    file_type: str
    message: str
