"""Excel import service — parse .xlsx files and create SQLite tables asynchronously."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

import aiosqlite

# SQLite reserved words that would cause syntax errors if used as column names.
_SQLITE_KEYWORDS = {
    "ABORT", "ACTION", "ADD", "AFTER", "ALL", "ALTER", "ANALYZE", "AND", "AS",
    "ASC", "ATTACH", "AUTOINCREMENT", "BEFORE", "BEGIN", "BETWEEN", "BY",
    "CASCADE", "CASE", "CAST", "CHECK", "COLLATE", "COLUMN", "COMMIT",
    "CONFLICT", "CONSTRAINT", "CREATE", "CROSS", "CURRENT", "DATABASE",
    "DEFAULT", "DEFERRABLE", "DEFERRED", "DELETE", "DESC", "DETACH",
    "DISTINCT", "DO", "DROP", "EACH", "ELSE", "END", "ESCAPE", "EXCEPT",
    "EXCLUSIVE", "EXISTS", "EXPLAIN", "FAIL", "FILTER", "FOLLOWING",
    "FOR", "FOREIGN", "FROM", "FULL", "GLOB", "GROUP", "HAVING", "IF",
    "IGNORE", "IMMEDIATE", "IN", "INDEX", "INDEXED", "INITIALLY", "INNER",
    "INSERT", "INSTEAD", "INTERSECT", "INTO", "IS", "ISNULL", "JOIN",
    "KEY", "LEFT", "LIKE", "LIMIT", "MATCH", "NATURAL", "NO", "NOT",
    "NOTHING", "NOTNULL", "NULL", "OF", "OFFSET", "ON", "OR", "ORDER",
    "OUTER", "OVER", "PARTITION", "PLAN", "PRAGMA", "PRECEDING", "PRIMARY",
    "QUERY", "RAISE", "RANGE", "RECURSIVE", "REFERENCES", "REGEXP",
    "REINDEX", "RELEASE", "RENAME", "REPLACE", "RESTRICT", "RIGHT",
    "ROLLBACK", "ROW", "ROWS", "SAVEPOINT", "SELECT", "SET", "TABLE",
    "TEMP", "TEMPORARY", "THEN", "TO", "TRANSACTION", "TRIGGER", "UNBOUNDED",
    "UNION", "UNIQUE", "UPDATE", "USING", "VACUUM", "VALUES", "VIEW",
    "VIRTUAL", "WHEN", "WHERE", "WINDOW", "WITH", "WITHOUT",
}

_TRACKING_TABLE = "_chatbi_uploads"


async def _ensure_tracking_table(db_path: str) -> None:
    """Create the upload tracking table if it doesn't exist."""
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT    NOT NULL,
                table_name        TEXT    NOT NULL UNIQUE,
                display_name      TEXT    NOT NULL,
                created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
                row_count         INTEGER NOT NULL DEFAULT 0,
                column_count      INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.commit()
    finally:
        await conn.close()


def sanitize_column_name(name: str) -> str:
    """Clean a column name for use as a SQLite column identifier."""
    # Normalize unicode and strip
    name = unicodedata.normalize("NFKC", name).strip()
    # Replace whitespace sequences with underscore
    name = re.sub(r"\s+", "_", name)
    # Remove remaining non-alphanumeric, non-underscore characters
    name = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]", "", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    # Fallback for empty result
    if not name:
        return "col"
    # If starts with digit, prefix with col_
    if name[0].isdigit():
        name = "col_" + name
    # Lowercase
    name = name.lower()
    # Handle SQLite reserved words
    if name.upper() in _SQLITE_KEYWORDS:
        name = name + "_"
    return name


def _infer_type(values: list[Any]) -> str:
    """Infer SQLite type affinity from a sample of values."""
    sample = [v for v in values if v is not None and v != ""][:100]
    if not sample:
        return "TEXT"

    all_int = True
    all_num = True
    for v in sample:
        if isinstance(v, bool):
            all_int = False
            all_num = False
        elif isinstance(v, int):
            pass
        elif isinstance(v, float):
            all_int = False
        else:
            # Try to coerce string representations
            try:
                float(v)
                all_int = False
            except (ValueError, TypeError):
                all_int = False
                all_num = False

    if all_int:
        return "INTEGER"
    if all_num:
        return "REAL"
    return "TEXT"


def _generate_table_name(original_filename: str) -> str:
    """Generate a unique table name from the original filename."""
    stem = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
    stem = sanitize_column_name(stem) or "data"
    if stem.upper() in _SQLITE_KEYWORDS:
        stem += "_"
    now = datetime.now(timezone.utc)
    return f"uploaded_{stem}_{now.strftime('%Y%m%d_%H%M%S')}"


def _parse_excel(file_bytes: bytes) -> list[dict]:
    """Parse an .xlsx file into a list of dicts. Called in a thread."""
    import io
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("Excel文件为空，没有工作表")

    rows_iter = ws.iter_rows(values_only=True)
    header_row = None
    for row in rows_iter:
        if any(v is not None for v in row):
            header_row = row
            break

    if header_row is None:
        raise ValueError("Excel文件没有表头行")

    headers = []
    for h in header_row:
        s = str(h).strip() if h is not None else ""
        sanitized = sanitize_column_name(s)
        # Ensure uniqueness
        base = sanitized
        counter = 1
        while sanitized in headers:
            sanitized = f"{base}_{counter}"
            counter += 1
        headers.append(sanitized)

    if not headers:
        raise ValueError("表头行没有有效的列名")

    data = []
    for row in rows_iter:
        if all(v is None for v in row):
            continue
        row_dict = {}
        for i, val in enumerate(row):
            if i < len(headers):
                # Convert openpyxl types to native Python types
                if val is None:
                    row_dict[headers[i]] = None
                elif isinstance(val, datetime):
                    row_dict[headers[i]] = val.isoformat()
                else:
                    row_dict[headers[i]] = val
        data.append(row_dict)

    wb.close()
    return data


async def import_excel(db_path: str, file_bytes: bytes, original_filename: str) -> dict:
    """Import an Excel file as a new SQLite table. Returns metadata."""
    if not original_filename.lower().endswith(".xlsx"):
        raise ValueError("只支持 .xlsx 格式的Excel文件")

    # Parse in thread to avoid blocking the event loop
    data = await asyncio.to_thread(_parse_excel, file_bytes)
    if not data:
        raise ValueError("Excel文件中没有数据行")

    columns = list(data[0].keys())
    if not columns:
        raise ValueError("未能解析出有效的列名")

    # Infer column types
    col_types: dict[str, str] = {}
    for col in columns:
        sample = [row.get(col) for row in data]
        col_types[col] = _infer_type(sample)

    table_name = _generate_table_name(original_filename)

    conn = await aiosqlite.connect(db_path)
    try:
        await _ensure_tracking_table(db_path)

        # Build CREATE TABLE DDL
        col_defs = ", ".join(f"[{col}] {col_types[col]}" for col in columns)
        ddl = f"CREATE TABLE IF NOT EXISTS [{table_name}] ({col_defs})"
        await conn.execute(ddl)

        # Batch insert
        placeholders = ", ".join("?" for _ in columns)
        quoted_cols = ", ".join(f"[{col}]" for col in columns)
        insert_sql = f"INSERT INTO [{table_name}] ({quoted_cols}) VALUES ({placeholders})"

        batch_size = 100
        for i in range(0, len(data), batch_size):
            batch = data[i : i + batch_size]
            rows = []
            for row in batch:
                rows.append(tuple(row.get(col) for col in columns))
            await conn.executemany(insert_sql, rows)

        # Ensure tracking table is accessible (re-get connection if needed)
        await conn.execute(
            f"INSERT INTO {_TRACKING_TABLE} (original_filename, table_name, display_name, row_count, column_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (original_filename, table_name, original_filename.rsplit(".", 1)[0], len(data), len(columns)),
        )
        await conn.commit()

        return {
            "table_name": table_name,
            "original_filename": original_filename,
            "display_name": original_filename.rsplit(".", 1)[0],
            "row_count": len(data),
            "column_count": len(columns),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def list_uploads(db_path: str) -> list[dict]:
    """List all uploaded tables."""
    await _ensure_tracking_table(db_path)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(
            f"SELECT * FROM {_TRACKING_TABLE} ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def delete_upload(db_path: str, table_name: str) -> None:
    """Delete an uploaded table and its tracking record."""
    await _ensure_tracking_table(db_path)
    conn = await aiosqlite.connect(db_path)
    try:
        # Verify the table exists in tracking
        cursor = await conn.execute(
            f"SELECT original_filename FROM {_TRACKING_TABLE} WHERE table_name = ?",
            (table_name,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"未找到上传表: {table_name}")

        # Drop the data table
        await conn.execute(f"DROP TABLE IF EXISTS [{table_name}]")
        # Remove tracking record
        await conn.execute(
            f"DELETE FROM {_TRACKING_TABLE} WHERE table_name = ?",
            (table_name,),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_uploaded_tables_schema(db_path: str) -> str:
    """Return a schema description of all uploaded tables for LLM context."""
    await _ensure_tracking_table(db_path)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(
            f"SELECT * FROM {_TRACKING_TABLE} ORDER BY created_at DESC"
        )
        uploads = await cursor.fetchall()
    finally:
        await conn.close()

    if not uploads:
        return ""

    lines = [""]
    table_num = 4  # Continue numbering after the 3 built-in tables

    for upload in uploads:
        table_name = upload["table_name"]
        display_name = upload["original_filename"]

        # Get column info for this table
        conn2 = await aiosqlite.connect(db_path)
        try:
            cursor2 = await conn2.execute(f"PRAGMA table_info([{table_name}])")
            cols = await cursor2.fetchall()
        finally:
            await conn2.close()

        lines.append(f"{table_num}. {table_name} (上传数据 - {display_name})")
        for c in cols:
            col_name = c[1]
            col_type = c[2]
            lines.append(f"   - {col_name}: {col_type}")
        table_num += 1

    return "\n".join(lines)
