"""LLM 客户端 - 用于理解用户意图 + 生成推荐解释"""
import json
import httpx
from typing import Optional
from app.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL


def _chat(messages: list, max_tokens: int = 500, temperature: float = 0.3) -> Optional[str]:
    """调用 LLM chat/completions"""
    if not LLM_API_KEY:
        return None
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json=payload,
            )
            if r.status_code != 200:
                return None
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def parse_user_intent(query: str) -> dict:
    """把自然语言需求解析成结构化查询条件

    返回: {"category": "...", "price_range": [min, max], "tags": [...], "keywords": "..."}
    """
    prompt = f"""你是电商推荐系统的意图解析器。用户说："{query}"

请提取以下信息，返回 JSON（不要其他文字）：
{{
  "category": "商品类目（电子/服装/食品/家居/运动/美妆/图书/其他）",
  "subcategory": "子类目（如手机/耳机/笔记本等，不确定填空串）",
  "price_range": [最低价, 最高价],
  "tags": ["标签1", "标签2"],
  "keywords": "核心关键词",
  "intent": "购买意图描述（一句话）"
}}
价格范围不确定填 [0, 99999]。"""
    result = _chat([{"role": "user", "content": prompt}], max_tokens=300)
    if not result:
        return {"category": "", "subcategory": "", "price_range": [0, 99999],
                "tags": [], "keywords": query, "intent": query}
    try:
        # 提取 JSON
        import re
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return {"category": "", "subcategory": "", "price_range": [0, 99999],
            "tags": [], "keywords": query, "intent": query}


def generate_explanation(query: str, items: list) -> str:
    """为推荐结果生成解释"""
    if not items:
        return "暂无匹配的商品推荐。"

    item_desc = "\n".join(
        f"- {i['name']}（{i['category']}，¥{i['price']:.0f}）：{i.get('description', '')[:50]}"
        for i in items[:5]
    )
    prompt = f"""你是电商推荐助手。用户需求："{query}"

推荐了以下商品：
{item_desc}

用2-3句话解释为什么推荐这些商品，语气友好自然。不要列点。"""
    result = _chat([{"role": "user", "content": prompt}], max_tokens=200)
    return result or f"根据您的需求「{query}」，为您推荐以下商品。"


def generate_user_summary(user_name: str, interactions: list) -> str:
    """根据用户行为生成偏好摘要"""
    if not interactions:
        return "新用户，暂无行为数据。"
    action_desc = "\n".join(
        f"- {i['action']}: {i['item_name']}（{i['category']}）"
        for i in interactions[:20]
    )
    prompt = f"""用户 {user_name} 的近期行为：
{action_desc}

用1-2句话总结该用户的偏好特征。"""
    result = _chat([{"role": "user", "content": prompt}], max_tokens=150)
    return result or "暂无分析。"
