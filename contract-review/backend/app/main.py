"""ContractReview — FastAPI application entry point."""

import sys
sys.setrecursionlimit(10000)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from .config import get_settings
from .services.db import init_db
from .routers import documents, knowledge_base, review

settings = get_settings()

# Initialize database on import
init_db()

app = FastAPI(
    title="ContractReview — 合同智能审核平台",
    version="1.0.0",
    description="上传PDF/Word合同，基于知识库标准条款进行智能审核与批注",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(documents.router)
app.include_router(knowledge_base.router)
app.include_router(review.router)


# Health check
@app.get("/api/health")
def health():
    import os
    db_path = settings.db_path
    db_size = db_path.stat().st_size if db_path.exists() else 0
    return {
        "status": "ok",
        "llm_configured": bool(settings.llm_api_key),
        "db_size": db_size,
    }


# Serve frontend
frontend_path = settings.project_root / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
