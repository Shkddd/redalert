"""LLM + 推荐系统 主入口"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from app.database import get_db
from app.seed_data import seed
from app.routers.recommend import router as rec_router

app = FastAPI(title="LLM Recommend", version="1.0")

# 静态文件
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/css", StaticFiles(directory=str(FRONTEND / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND / "js")), name="js")

app.include_router(rec_router)


@app.on_event("startup")
def startup():
    result = seed()
    print(f"[seed] {result}")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND / "index.html"))


@app.get("/api/items")
def api_items():
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, category, subcategory, price, tags FROM items ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/users")
def api_users():
    with get_db() as conn:
        rows = conn.execute("SELECT id, username, display_name, preferences FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/interact")
def api_interact(user_id: int, item_id: int, action: str = "view"):
    """记录用户交互"""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO interactions (user_id, item_id, action) VALUES (?,?,?)",
            (user_id, item_id, action),
        )
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
