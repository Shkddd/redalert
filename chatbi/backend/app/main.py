"""ChatBI — FastAPI application entry point."""

from __future__ import annotations
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure backend/ is on path for data.seed_data import
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from .config import get_settings
from .routers import chat

app = FastAPI(
    title="ChatBI — 自然语言数据查询",
    description="用自然语言问数据，自动生成SQL并返回结果+图表",
    version="1.0.0",
)

# CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(chat.router, prefix="/api")

# Serve frontend static files
_frontend = Path(__file__).parent.parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


@app.on_event("startup")
async def startup():
    """Seed the database on first startup."""
    from data.seed_data import seed_database
    import aiosqlite
    db_path = settings.db_path
    seeded = seed_database(db_path, num_orders=settings.seed_data_size)
    if seeded:
        conn = await aiosqlite.connect(db_path)
        row = await (await conn.execute("SELECT COUNT(*) FROM orders")).fetchone()
        count = row[0] if row else 0
        await conn.close()
        print(f"Database initialized — {count} orders")
    else:
        print("Database already exists, skipping seed")


@app.get("/api/ping")
async def ping():
    return {"pong": True}
