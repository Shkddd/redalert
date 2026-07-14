"""Execute SQL queries against SQLite (async) and format results for display + charts."""

from __future__ import annotations
import aiosqlite
import re
import time
from typing import Any


# Safety: only allow SELECT-like statements
_SAFE_SQL_RE = re.compile(r'^\s*SELECT\b', re.IGNORECASE)
_FORBIDDEN_KEYWORDS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXEC|ATTACH|DETACH|REINDEX|REPLACE|TRUNCATE|VACUUM)\b',
    re.IGNORECASE
)


def _validate_sql(sql: str) -> str | None:
    """Returns None if valid, error message string if invalid."""
    if not sql or not sql.strip():
        return "SQL语句为空"
    if not _SAFE_SQL_RE.match(sql):
        return "只允许SELECT查询"
    if _FORBIDDEN_KEYWORDS.search(sql):
        return "禁止使用INSERT/UPDATE/DELETE/DROP等写操作语句"
    return None


async def execute_query(db_path: str, sql: str) -> dict[str, Any]:
    """Execute a SQL query asynchronously and return structured results."""
    error = _validate_sql(sql)
    if error:
        return {"error": error, "data": [], "columns": []}

    start = time.time()
    try:
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(sql)
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        data = [dict(row) for row in rows]
        await conn.close()

        elapsed = (time.time() - start) * 1000

        return {
            "data": data,
            "columns": columns,
            "row_count": len(data),
            "execution_time_ms": round(elapsed, 1),
            "error": None,
        }
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {
            "error": f"SQL执行错误: {str(e)}",
            "data": [],
            "columns": [],
            "execution_time_ms": round(elapsed, 1),
        }


def build_chart_data(
    data: list[dict[str, Any]],
    columns: list[str],
    visualization: str | None,
) -> dict[str, Any] | None:
    """
    Transform query results into chart-friendly format.
    Returns None if data is empty or doesn't support charts.
    """
    if not data or not columns:
        return None

    if not visualization or visualization == "table":
        if len(columns) >= 2:
            first_col_vals = [str(r[columns[0]]) for r in data[:10]]
            second_col_vals = []
            for r in data[:10]:
                v = r[columns[1]]
                if isinstance(v, (int, float)):
                    second_col_vals.append(v)
                else:
                    try:
                        second_col_vals.append(float(v))
                    except (ValueError, TypeError):
                        second_col_vals.append(None)

            if len(second_col_vals) == len(data[:10]) and all(v is not None for v in second_col_vals):
                if any(_looks_like_date(v) for v in first_col_vals):
                    visualization = "line"
                elif len(data) <= 15:
                    visualization = "bar"
                else:
                    visualization = "bar"
            else:
                visualization = "table"
        else:
            visualization = "table"

    chart = {
        "type": visualization,
        "labels": [],
        "datasets": [],
    }

    if visualization == "pie":
        chart["labels"] = [str(r[columns[0]]) for r in data]
        chart["datasets"] = [{
            "label": columns[1] if len(columns) > 1 else "值",
            "data": [float(r[columns[1]]) if isinstance(r[columns[1]], (int, float)) else 0 for r in data],
        }]
    elif visualization in ("bar", "line"):
        chart["labels"] = [str(r[columns[0]]) for r in data]
        available_cols = columns[1:4]
        chart["datasets"] = []
        for col in available_cols:
            vals = []
            for r in data:
                v = r[col]
                if isinstance(v, (int, float)):
                    vals.append(v)
                else:
                    try:
                        vals.append(float(v))
                    except (ValueError, TypeError):
                        vals.append(None)
            if any(v is not None for v in vals):
                chart["datasets"].append({
                    "label": col,
                    "data": vals,
                })
    else:
        return None

    return chart


def _looks_like_date(s: str) -> bool:
    """Check if a string looks like a date."""
    patterns = [
        r'^\d{4}-\d{2}$',
        r'^\d{4}-\d{2}-\d{2}$',
        r'^\d{4}年\d{1,2}月',
        r'^\d{4}-Q[1-4]',
    ]
    return any(re.match(p, s) for p in patterns)
