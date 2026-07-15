"""
推荐引擎核心 - 三路召回 + LLM 排序解释

1. 协同过滤: 用户-物品交互矩阵 → 相似用户喜欢什么
2. 内容语义: BGE embedding 余弦相似度
3. LLM 意图: 自然语言理解 → 结构化过滤

最终: 三路合并 → 加权排序 → LLM 生成推荐理由
"""
import json
import numpy as np
from typing import List, Dict, Optional
from app.database import get_db
from app.embedder import embed_text, cosine_sim_batch


# ── 1. 协同过滤 ──────────────────────────────────────
def collaborative_filter(user_id: int, top_k: int = 10) -> List[dict]:
    """基于用户的协同过滤: 找相似用户 → 推他们喜欢的东西"""
    with get_db() as conn:
        # 当前用户的交互
        my_actions = conn.execute(
            """SELECT item_id, action, score FROM interactions WHERE user_id=?""",
            (user_id,),
        ).fetchall()
    if not my_actions:
        return []

    my_items = {r["item_id"]: _action_score(r["action"], r["score"]) for r in my_actions}

    with get_db() as conn:
        # 所有其他用户的交互
        others = conn.execute(
            """SELECT user_id, item_id, action, score FROM interactions WHERE user_id!=?""",
            (user_id,),
        ).fetchall()

    if not others:
        return []

    # 计算用户相似度(共同交互物品的评分相关性)
    user_items = {}
    for r in others:
        uid = r["user_id"]
        if uid not in user_items:
            user_items[uid] = {}
        user_items[uid][r["item_id"]] = _action_score(r["action"], r["score"])

    # 相似度 = 共同物品的评分点积
    similarities = {}
    for uid, items in user_items.items():
        common = set(my_items.keys()) & set(items.keys())
        if not common:
            continue
        sim = sum(my_items[i] * items[i] for i in common)
        sim /= (len(common) ** 0.5)  # 归一化
        similarities[uid] = sim

    if not similarities:
        return []

    # 取最相似的 K 个用户
    top_users = sorted(similarities.items(), key=lambda x: -x[1])[:10]

    # 收集他们喜欢的、我没交互过的物品
    candidates = {}
    for uid, sim in top_users:
        for iid, score in user_items[uid].items():
            if iid not in my_items:
                candidates[iid] = candidates.get(iid, 0) + sim * score

    # 排序取 top_k
    ranked = sorted(candidates.items(), key=lambda x: -x[1])[:top_k]
    return [{"item_id": iid, "cf_score": score} for iid, score in ranked]


def _action_score(action: str, base_score: float = 1.0) -> float:
    """行为 → 权重"""
    weights = {"purchase": 5.0, "like": 3.0, "cart": 2.0, "view": 1.0, "click": 0.5}
    return weights.get(action, 1.0) * base_score


# ── 2. 语义匹配 ──────────────────────────────────────
def semantic_search(query: str, top_k: int = 10) -> List[dict]:
    """query embedding vs 所有商品 embedding → 余弦相似度排序"""
    query_vec = embed_text(query)

    with get_db() as conn:
        items = conn.execute("SELECT id, name, category, description, tags, embedding FROM items").fetchall()

    if not items:
        return []

    # 加载已有 embedding
    ids, vecs = [], []
    for item in items:
        if item["embedding"]:
            ids.append(item["id"])
            vecs.append(np.frombuffer(item["embedding"], dtype=np.float32))

    if not vecs:
        return []

    matrix = np.stack(vecs)
    sims = cosine_sim_batch(query_vec, matrix)
    ranked_idx = np.argsort(-sims)[:top_k]

    return [{"item_id": ids[i], "semantic_score": float(sims[i])} for i in ranked_idx]


# ── 3. LLM 意图过滤 ─────────────────────────────────
def intent_filter(query: str, top_k: int = 10) -> List[dict]:
    """LLM 解析意图 → 结构化条件 → SQL 过滤"""
    from app.llm_client import parse_user_intent
    intent = parse_user_intent(query)

    conditions = []
    params = []

    if intent.get("category"):
        conditions.append("category=?")
        params.append(intent["category"])

    price_range = intent.get("price_range", [0, 99999])
    if price_range and len(price_range) == 2:
        if price_range[0] > 0:
            conditions.append("price>=?")
            params.append(price_range[0])
        if price_range[1] < 99999:
            conditions.append("price<=?")
            params.append(price_range[1])

    tags = intent.get("tags", [])
    if tags:
        for tag in tags[:3]:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")

    keywords = intent.get("keywords", "")
    if keywords and not conditions:
        conditions.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
        params.extend([f"%{keywords}%"] * 3)

    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"SELECT id, name, category, price FROM items WHERE {where} ORDER BY id DESC LIMIT ?"
    params.append(top_k)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [{"item_id": r["id"], "intent_score": 1.0} for r in rows]


# ── 融合推荐 ─────────────────────────────────────────
def recommend(user_id: int, query: str = "", top_k: int = 6) -> dict:
    """三路召回 + 融合排序

    返回: {"items": [...], "explanation": "...", "strategy": "..."}
    """
    cf_results = collaborative_filter(user_id, top_k=top_k * 2)
    sem_results = semantic_search(query, top_k=top_k * 2) if query else []
    int_results = intent_filter(query, top_k=top_k * 2) if query else []

    # 融合打分: 加权求和
    scores = {}
    # 协同过滤权重 0.3
    for r in cf_results:
        scores[r["item_id"]] = scores.get(r["item_id"], 0) + r["cf_score"] * 0.3
    # 语义匹配权重 0.4
    for r in sem_results:
        scores[r["item_id"]] = scores.get(r["item_id"], 0) + r["semantic_score"] * 0.4
    # 意图过滤权重 0.3
    for r in int_results:
        scores[r["item_id"]] = scores.get(r["item_id"], 0) + r["intent_score"] * 0.3

    if not scores:
        # 无行为数据时 fallback 到热门商品
        with get_db() as conn:
            rows = conn.execute("""
                SELECT i.id, i.name, i.category, i.price, i.description, i.tags,
                       COUNT(it.id) as popularity
                FROM items i LEFT JOIN interactions it ON i.id = it.item_id
                GROUP BY i.id ORDER BY popularity DESC LIMIT ?
            """, (top_k,)).fetchall()
        items = [dict(r) for r in rows]
        return {"items": items, "explanation": "您是新用户，为您推荐热门商品。", "strategy": "popular"}

    # 取 top_k
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    item_ids = [iid for iid, _ in ranked]

    # 查商品详情
    placeholders = ",".join("?" * len(item_ids))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM items WHERE id IN ({placeholders})", item_ids
        ).fetchall()

    items_by_id = {r["id"]: dict(r) for r in rows}
    items = [items_by_id[iid] for iid in item_ids if iid in items_by_id]

    # 加融合分
    for item in items:
        item["_score"] = round(scores.get(item["id"], 0), 3)

    # LLM 生成推荐解释
    from app.llm_client import generate_explanation
    explanation = generate_explanation(query or "个性化推荐", items)

    strategies = []
    if cf_results:
        strategies.append("协同过滤")
    if sem_results:
        strategies.append("语义匹配")
    if int_results:
        strategies.append("意图理解")

    return {
        "items": items,
        "explanation": explanation,
        "strategy": "+".join(strategies) if strategies else "热门推荐",
    }


# ── 用户画像 ─────────────────────────────────────────
def get_user_profile(user_id: int) -> dict:
    """获取用户偏好画像"""
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            return {}

        # 统计行为
        actions = conn.execute("""
            SELECT it.action, COUNT(*) as cnt, i.category
            FROM interactions it JOIN items i ON it.item_id = i.id
            WHERE it.user_id=?
            GROUP BY it.action, i.category
            ORDER BY cnt DESC
        """, (user_id,)).fetchall()

        # 最近交互
        recent = conn.execute("""
            SELECT i.name, i.category, it.action, it.created_at
            FROM interactions it JOIN items i ON it.item_id = i.id
            WHERE it.user_id=?
            ORDER BY it.created_at DESC LIMIT 20
        """, (user_id,)).fetchall()

    return {
        "user": dict(user),
        "action_stats": [dict(r) for r in actions],
        "recent": [dict(r) for r in recent],
    }
