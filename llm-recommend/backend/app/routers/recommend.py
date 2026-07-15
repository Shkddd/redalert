"""推荐 API"""
from fastapi import APIRouter, Query
from app.recommender import recommend, get_user_profile, semantic_search, collaborative_filter
from app.llm_client import generate_user_summary
from app.database import get_db

router = APIRouter()


@router.get("/api/recommend/{user_id}")
def api_recommend(
    user_id: int,
    q: str = Query("", description="自然语言需求"),
    top_k: int = Query(6, ge=1, le=20),
):
    """核心推荐接口

    - user_id=0 为匿名用户(只走语义+意图,不走协同过滤)
    - q 为空时走个性化推荐(协同过滤+热门)
    - q 非空时三路融合
    """
    result = recommend(user_id, query=q, top_k=top_k)
    return {
        "user_id": user_id,
        "query": q,
        "strategy": result["strategy"],
        "explanation": result["explanation"],
        "items": [
            {k: v for k, v in item.items() if not k.startswith("_")}
            for item in result["items"]
        ],
        "count": len(result["items"]),
    }


@router.get("/api/profile/{user_id}")
def api_profile(user_id: int):
    """用户画像"""
    profile = get_user_profile(user_id)
    if not profile:
        return {"error": "user not found"}
    # LLM 生成偏好摘要
    summary = generate_user_summary(
        profile["user"]["display_name"],
        profile["recent"],
    )
    profile["summary"] = summary
    return profile


@router.get("/api/search")
def api_search(q: str = Query(...), top_k: int = Query(10)):
    """纯语义搜索"""
    results = semantic_search(q, top_k=top_k)
    if not results:
        return {"results": [], "count": 0}
    item_ids = [r["item_id"] for r in results]
    placeholders = ",".join("?" * len(item_ids))
    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM items WHERE id IN ({placeholders})", item_ids).fetchall()
    items_by_id = {r["id"]: dict(r) for r in rows}
    items = []
    for r in results:
        item = items_by_id.get(r["item_id"])
        if item:
            item["score"] = round(r["semantic_score"], 3)
            items.append(item)
    return {"results": items, "count": len(items)}
