"""
Excel sheet → Markdown 表格
- 每个 sheet 一个 Page,text 字段 = markdown 表格
- section_path = "{文件名} > {sheet 名}"
- raw_meta: {'sheet_name': ..., 'rows': ..., 'cols': ...}
"""
from pathlib import Path
from typing import List

from openpyxl import load_workbook

from app.ingest.parser_pdf import Page, _clean_text


def _cell_to_str(c) -> str:
    if c is None:
        return ""
    s = str(c).strip()
    # 处理换行 / 多余空白
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) > 200:
        s = s[:200] + "..."
    # markdown 表格里的竖线需要转义
    s = s.replace("|", "\\|")
    return s


def sheet_to_markdown(ws) -> str:
    """sheet → markdown 表格(首行为表头)"""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return ""
    # 找首行非空作为表头
    header_idx = 0
    for i, r in enumerate(rows[:5]):
        if any(_cell_to_str(c) for c in r):
            header_idx = i
            break
    header = [_cell_to_str(c) for c in rows[header_idx]]
    if not any(header):
        return ""

    body = []
    for r in rows[header_idx + 1:]:
        cells = [_cell_to_str(c) for c in r]
        if any(cells):
            body.append(cells)

    # 表头列数对齐
    n_cols = max(len(header), max((len(r) for r in body), default=0))
    while len(header) < n_cols:
        header.append("")
    for r in body:
        while len(r) < n_cols:
            r.append("")

    md_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * n_cols) + " |",
    ]
    for r in body:
        md_lines.append("| " + " | ".join(r) + " |")
    return "\n".join(md_lines)


def parse_excel(path: Path) -> List[Page]:
    path = Path(path)
    wb = load_workbook(str(path), data_only=True, read_only=True)
    pages: List[Page] = []
    try:
        for idx, sheet_name in enumerate(wb.sheetnames, 1):
            ws = wb[sheet_name]
            md = sheet_to_markdown(ws)
            md = _clean_text(md)
            if not md:
                continue
            section = f"{path.stem} > {sheet_name}"
            pages.append(Page(
                page_no=idx,  # 用 sheet 序号当 page_no 方便
                text=md,
                images=[],
                section_path=section,
                raw_meta={"sheet_name": sheet_name, "format": "xlsx"},
            ))
        if not pages:
            pages.append(Page(page_no=1, text="", section_path=path.stem,
                              raw_meta={"format": "xlsx"}))
    finally:
        wb.close()
    return pages


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    pages = parse_excel(p)
    print(f"parsed {len(pages)} sheets from {p.name}")
    for pg in pages:
        print(f"\n--- {pg.section_path} ---")
        print(pg.text[:400])
