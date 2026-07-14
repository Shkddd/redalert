"""
LLM 总结:用召回的 chunks 生成最终答案 + 来源标注

输入: 召回 hits(每条带 doc_title/section_path/image_url/category/version_id)
输出: {answer: str, sources: [...]}
"""
import os
from typing import List, Dict, Any
import httpx

from app.core.config import LLM_MODEL_DEFAULT, LLM_TIMEOUT_S, SUMMARY_PROMPT


def _get_llm_config() -> tuple:
    base_url = os.getenv("LLM_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
    # 兼容 /anthropic 路径
    base_url = base_url.replace("/anthropic", "")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("MINIMAX_CN_API_KEY")
    model = os.getenv("LLM_MODEL", LLM_MODEL_DEFAULT)
    return base_url, api_key, model


def _format_sources(hits: List[dict]) -> str:
    """把召回结果格式化为来源列表(给 LLM 当 context)"""
    if not hits:
        return "（无召回结果）"
    blocks = []
    for i, h in enumerate(hits, 1):
        img = ""
        if h.get("image_url"):
            img = f"\n图片: {h['image_url']}"
        blocks.append(
            f"[来源 {i}] 文档={h.get('doc_title', '?')} "
            f"章节={h.get('section_path', '?')} "
            f"页码={h.get('page', '?')} "
            f"业务={h.get('category', '?')} "
            f"版本id={h.get('version_id', '?')}"
            f"{img}\n"
            f"正文: {h.get('text', '')[:400]}"
        )
    return "\n\n".join(blocks)


SYSTEM_PROMPT = (
    "你是一个严谨的 RAG 助手。回答用户问题时:\n"
    "1. 只能基于【召回来源】里的内容回答,不要编造\n"
    "2. 在答案末尾用 [来源 N] 标注引用的来源编号\n"
    "3. 如果召回里包含图片,在相关答案处用 ![](URL) 嵌入图片\n"
    "4. 如果召回信息不足以回答,直接说'未找到相关信息'\n"
    "5. 用中文回答,简洁准确"
)


def synthesize(query: str, hits: List[dict]) -> Dict[str, Any]:
    """
    调用 LLM 生成最终总结 + 标注来源
    失败时降级为简单拼接
    """
    base_url, api_key, model = _get_llm_config()
    sources_text = _format_sources(hits)

    # 降级路径:没配 API key
    if not api_key:
        return {
            "answer": _simple_summary(query, hits),
            "sources": _build_sources_meta(hits),
            "model": None,
            "fallback": True,
        }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                f"用户问题: {query}\n\n"
                f"召回来源({len(hits)} 条):\n{sources_text}\n\n"
                f"请基于以上来源回答用户问题。"},
        ],
        "max_tokens": 800,
        "temperature": 0.2,
    }
    try:
        with httpx.Client(timeout=LLM_TIMEOUT_S) as client:
            r = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if r.status_code != 200:
                return {
                    "answer": _simple_summary(query, hits),
                    "sources": _build_sources_meta(hits),
                    "model": model,
                    "fallback": True,
                    "error": f"HTTP {r.status_code}",
                }
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            answer = content.strip() if isinstance(content, str) else str(content)
            return {
                "answer": answer,
                "sources": _build_sources_meta(hits),
                "model": model,
                "fallback": False,
            }
    except Exception as e:
        return {
            "answer": _simple_summary(query, hits),
            "sources": _build_sources_meta(hits),
            "model": model,
            "fallback": True,
            "error": f"{type(e).__name__}: {str(e)[:100]}",
        }


def _simple_summary(query: str, hits: List[dict]) -> str:
    """无 LLM 时的降级总结:拼接 top hits + 标注"""
    if not hits:
        return f"未找到与「{query}」相关的信息。"
    lines = [f"关于「{query}」的检索结果(共 {len(hits)} 条,按相关度排序):\n"]
    for i, h in enumerate(hits, 1):
        img_note = ""
        if h.get("image_url"):
            img_note = f"\n📷 图片: {h['image_url']}"
        lines.append(
            f"[来源 {i}] {h.get('doc_title', '?')} / "
            f"{h.get('section_path', '?')} / 第 {h.get('page', '?')} 页 / "
            f"{h.get('category', '?')}{img_note}\n"
            f"{h.get('text', '').strip()[:300]}"
        )
    return "\n\n".join(lines)


def _build_sources_meta(hits: List[dict]) -> List[dict]:
    """结构化来源列表(给前端展示用)"""
    out = []
    for i, h in enumerate(hits, 1):
        out.append({
            "index": i,
            "chunk_id": h.get("chunk_id"),
            "doc_title": h.get("doc_title"),
            "section_path": h.get("section_path"),
            "page": h.get("page"),
            "category": h.get("category"),
            "version_id": h.get("version_id"),
            "image_id": h.get("image_id") or None,
            "image_url": h.get("image_url") or None,
            "rrf_score": h.get("rrf_score"),
        })
    return out


# 兼容别名
simple_synthesize = synthesize
