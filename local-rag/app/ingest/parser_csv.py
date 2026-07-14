"""
CSV → Markdown 表格
- 首行为表头
- 大行数自动分页(每 CHUNK_ROWS 行一页)
- section_path = "{文件名}" 或 "{文件名} (part N)"
"""
import csv
from pathlib import Path
from typing import List

from app.ingest.parser_pdf import Page, _clean_text

# 超过此行数自动分页
CHUNK_ROWS = 200


def _cell_to_str(c) -> str:
    if c is None:
        return ""
    s = str(c).strip()
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) > 200:
        s = s[:200] + "..."
    s = s.replace("|", "\\|")
    return s


def _detect_encoding(path: Path) -> str:
    """尝试常见编码"""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312", "gb18030", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                f.read(4096)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"


def _rows_to_markdown(header: list, rows: list) -> str:
    """表头 + 数据行 → markdown 表格字符串"""
    if not header:
        return ""
    n_cols = len(header)
    for r in rows:
        if len(r) > n_cols:
            n_cols = len(r)
    # 对齐列数
    header = header + [""] * (n_cols - len(header))
    for r in rows:
        while len(r) < n_cols:
            r.append("")

    md = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * n_cols) + " |",
    ]
    for r in rows:
        md.append("| " + " | ".join(r) + " |")
    return "\n".join(md)


def parse_csv(path: Path) -> List[Page]:
    path = Path(path)
    enc = _detect_encoding(path)

    with open(path, encoding=enc, newline="") as f:
        # 先 sniff dialect
        sample = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(f, dialect)
        all_rows = list(reader)

    if not all_rows:
        return [Page(page_no=1, text="", section_path=path.stem,
                     raw_meta={"format": "csv"})]

    header = [_cell_to_str(c) for c in all_rows[0]]
    data_rows = [[_cell_to_str(c) for c in row] for row in all_rows[1:]]

    # 过滤全空行
    data_rows = [r for r in data_rows if any(r)]

    if not data_rows:
        md = _rows_to_markdown(header, [])
        md = _clean_text(md)
        return [Page(page_no=1, text=md, section_path=path.stem,
                     raw_meta={"format": "csv", "total_rows": 0})]

    # 分页
    pages: List[Page] = []
    total = len(data_rows)
    if total <= CHUNK_ROWS:
        md = _rows_to_markdown(header, data_rows)
        md = _clean_text(md)
        if md:
            pages.append(Page(
                page_no=1, text=md, section_path=path.stem,
                raw_meta={"format": "csv", "total_rows": total},
            ))
    else:
        part = 1
        for start in range(0, total, CHUNK_ROWS):
            chunk = data_rows[start:start + CHUNK_ROWS]
            md = _rows_to_markdown(header, chunk)
            md = _clean_text(md)
            if md:
                suffix = f" (part {part})" if total > CHUNK_ROWS else ""
                pages.append(Page(
                    page_no=part, text=md,
                    section_path=f"{path.stem}{suffix}",
                    raw_meta={"format": "csv", "total_rows": total,
                              "part": part},
                ))
                part += 1

    if not pages:
        pages.append(Page(page_no=1, text="", section_path=path.stem,
                          raw_meta={"format": "csv"}))
    return pages


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    pages = parse_csv(p)
    print(f"parsed {len(pages)} page(s) from {p.name}")
    for pg in pages:
        lines = pg.text.split("\n")
        print(f"\n--- {pg.section_path} ({len(lines)} lines) ---")
        print("\n".join(lines[:10]))
        if len(lines) > 10:
            print(f"... ({len(lines) - 10} more lines)")
