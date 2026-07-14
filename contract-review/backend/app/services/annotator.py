"""Annotator — compare contract clauses against knowledge base using LLM + RAG."""
import json
import re
from typing import Optional, List, Dict
from datetime import datetime

from .db import get_db
from ..config import get_settings
from .knowledge_base import hybrid_search


def run_review(doc_id: int) -> dict:
    """Run a full review: batch-analyze all clauses against KB (vector + BM25 + legacy)."""
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        raise ValueError(f"Document {doc_id} not found")

    clauses = db.execute(
        "SELECT * FROM clauses WHERE doc_id = ? ORDER BY clause_index", (doc_id,)
    ).fetchall()

    # Clear previous annotations and review
    for c in clauses:
        db.execute("DELETE FROM annotations WHERE clause_id = ?", (c["id"],))
    db.execute("DELETE FROM reviews WHERE doc_id = ?", (doc_id,))
    db.commit()

    review_id = db.execute(
        "INSERT INTO reviews (doc_id, status, total_clauses) VALUES (?, 'running', ?)",
        (doc_id, len(clauses)),
    ).lastrowid
    db.commit()

    settings = get_settings()

    # ── Build batch payload: hybrid-search KB for each clause ──
    clause_batch = []
    for clause in clauses:
        # Hybrid search: vector + BM25 across imported docs + legacy KB entries
        kb_matches = hybrid_search(clause["content"], top_k=4)
        clause_batch.append({
            "index": clause["clause_index"],
            "id": clause["id"],
            "text": clause["content"],
            "kb_matches": kb_matches,
        })

    # ── Batch LLM call for all clauses at once ──
    if settings.llm_api_key:
        analyses = _batch_analyze_clauses(clause_batch, settings)
    else:
        analyses = {}
        for item in clause_batch:
            if item["kb_matches"]:
                m = item["kb_matches"][0]
                analyses[item["index"]] = {
                    "match_type": "match",
                    "risk_level": "中",
                    "comment": f"与知识库相关（来源：{m.get('source_type', 'legacy_kb')}）",
                    "suggestion": "请人工审核",
                }

    # ── Save annotations ──
    matched = conflicted = missing = 0
    high = med = low = 0

    for item in clause_batch:
        idx = item["index"]
        analysis = analyses.get(idx)
        if not analysis:
            continue

        kb = item["kb_matches"]
        # Use first KB match for the annotation's kb_entry_id reference
        first = kb[0] if kb else None
        kb_id = first.get("id") if first and isinstance(first.get("id"), int) else None
        kb_title = ""
        if first:
            if first.get("source_type") == "legacy_kb":
                kb_title = first.get("title", "")
            else:
                # Vector chunk — use first 60 chars as "title"
                kb_title = first.get("content", "")[:60] + "..."

        db.execute(
            "INSERT INTO annotations (clause_id, kb_entry_id, kb_title, match_type, risk_level, comment, suggestion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item["id"],
                kb_id,
                kb_title,
                analysis["match_type"],
                analysis["risk_level"],
                analysis.get("comment", "")[:500],
                analysis.get("suggestion", "")[:500],
            ),
        )

        if analysis["match_type"] == "conflict":
            conflicted += 1
        elif analysis["match_type"] == "match":
            matched += 1
        else:
            missing += 1

        rl = analysis["risk_level"]
        if rl == "高":
            high += 1
        elif rl == "中":
            med += 1
        else:
            low += 1

    db.execute(
        "UPDATE reviews SET status = 'completed', matched = ?, conflicted = ?, missing_info = ?, "
        "high_risk = ?, medium_risk = ?, low_risk = ? WHERE id = ?",
        (matched, conflicted, missing, high, med, low, review_id),
    )
    db.commit()

    return get_review_result(doc_id)


def _batch_analyze_clauses(clause_batch: List[dict], settings) -> dict[int, dict]:
    """Send ALL clauses to LLM with retrieved KB context in one call."""
    import httpx, json, re

    kb_section = ""
    for item in clause_batch:
        kb_section += f"\n### 条款 {item['index']}\n"
        kb_section += f"内容：{item['text'][:1500]}\n"
        if item["kb_matches"]:
            for i, m in enumerate(item["kb_matches"]):
                source = m.get("source_type", "legacy_kb") if "source_type" in m else "legacy_kb"
                title = m.get("title", "") if "title" in m else ""
                content = m.get("content", "")[:500]
                score = m.get("score", 0)
                kb_section += (
                    f"  参考 {i+1}（来源:{source}, 相关度:{score:.2f}）\n"
                    f"    {content}\n"
                )
        else:
            kb_section += "  匹配参考：无\n"

    prompt = f"""你是一名资深合同审核专家。请批量审核以下{len(clause_batch)}个合同条款，逐个与知识库中的参考条款进行比对。

{ kb_section }

请返回 JSON 数组，每个元素对应一个条款：
[
  {{
    "index": 条款序号,
    "match_type": "match"或"conflict"或"missing",
    "risk_level": "高"或"中"或"低",
    "comment": "具体的审核意见（指出差异或风险点）",
    "suggestion": "具体的修改建议"
  }}
]

判断规则：
- match: 条款与参考条款基本一致
- conflict: 条款与参考条款存在冲突或对己方不利
- missing: 条款缺少必要内容（不可直接判定 match/conflict 时）

覆盖全部 {len(clause_batch)} 个条款。只输出 JSON，不要多余文字。"""

    try:
        resp = httpx.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": "你是资深合同审核专家，擅长批量识别合同风险。输出纯 JSON 数组。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=120,
        )
        result = resp.json()
        content = result["choices"][0]["message"]["content"]

        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            arr = json.loads(json_match.group())
            return {item["index"]: item for item in arr}
    except Exception as e:
        print(f"Batch LLM error: {e}")

    return {}


def analyze_clause_with_llm(clause_text: str, kb_matches: List[dict], settings) -> dict:
    """Use LLM to analyze a single clause against KB entries (fallback)."""
    if not kb_matches:
        return {"match_type": "missing", "risk_level": "中",
                "comment": "未在知识库中找到匹配的参考条款", "suggestion": "请人工审核"}

    kb_context = "\n\n".join([
        f"[参考 {i+1}] {'(来源:' + m.get('source_type','legacy_kb') + ')' if m.get('source_type') else ''}\n{m.get('content','')[:500]}"
        for i, m in enumerate(kb_matches)
    ])

    prompt = f"""你是一名资深合同审核专家。请审核以下合同条款，与知识库参考条款进行比对。

【合同条款】
{clause_text[:2000]}

【相关参考条款】
{kb_context}

请返回 JSON：
{{
  "match_type": "match" 或 "conflict" 或 "missing",
  "risk_level": "高" 或 "中" 或 "低",
  "comment": "具体的审核意见",
  "suggestion": "具体的修改建议"
}}

判断规则：
- match: 一致
- conflict: 存在冲突
- missing: 缺少必要内容

只输出 JSON。"""

    try:
        import httpx
        resp = httpx.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "system", "content": "你是资深合同审核专家。"},
                             {"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            analysis = json.loads(json_match.group())
            return {
                "match_type": analysis.get("match_type", "match"),
                "risk_level": analysis.get("risk_level", "中"),
                "comment": analysis.get("comment", ""),
                "suggestion": analysis.get("suggestion", ""),
            }
    except Exception:
        pass

    return {"match_type": "match", "risk_level": "中",
            "comment": "AI 分析失败，请人工审核", "suggestion": "请人工确认"}


def get_review_result(doc_id: int) -> dict:
    """Get full review result for a document."""
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    review = db.execute("SELECT * FROM reviews WHERE doc_id = ? ORDER BY id DESC", (doc_id,)).fetchone()

    if not review:
        return {"status": "pending", "doc_id": doc_id}

    annotations = db.execute("""
        SELECT a.*, c.clause_index, c.content as clause_content, c.page_number
        FROM annotations a
        JOIN clauses c ON a.clause_id = c.id
        WHERE c.doc_id = ?
        ORDER BY c.clause_index
    """, (doc_id,)).fetchall()

    return {
        "doc_id": doc_id,
        "doc_name": doc["original_name"],
        "status": review["status"],
        "total_clauses": review["total_clauses"],
        "matched": review["matched"],
        "conflicted": review["conflicted"],
        "missing": review["missing_info"],
        "high_risk": review["high_risk"],
        "medium_risk": review["medium_risk"],
        "low_risk": review["low_risk"],
        "annotations": [dict(a) for a in annotations],
        "created_at": review["created_at"],
    }
