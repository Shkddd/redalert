"""
Word(.docx) 解析
- 用 python-docx 抽段落
- 按 heading 样式累积 section_path
- 表格作为纯文本段落处理(以 markdown 表格形式)
"""
from pathlib import Path
from typing import List
from docx import Document

from app.ingest.parser_pdf import Page, _clean_text


def _table_to_text(table) -> str:
    rows = []
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_docx(path: Path) -> List[Page]:
    path = Path(path)
    doc = Document(str(path))
    pages: List[Page] = []

    # Word 不分页,我们按 "内容块" 分页:每 1500 字符或遇到 Heading1 时切页
    cur_text_parts: List[str] = []
    cur_section = path.stem  # 默认 section = 文件名
    cur_page_no = 1
    PAGE_CHAR_BUDGET = 1500

    def flush(reason: str = ""):
        nonlocal cur_text_parts, cur_page_no
        text = _clean_text("\n".join(cur_text_parts))
        if text:
            pages.append(Page(
                page_no=cur_page_no,
                text=text,
                section_path=cur_section,
                raw_meta={"reason": reason} if reason else {},
            ))
            cur_page_no += 1
        cur_text_parts = []

    # 段落
    for para in doc.paragraphs:
        style = (para.style.name or "").lower() if para.style else ""
        txt = para.text.strip()
        is_heading = "heading" in style or style.startswith("title")
        if is_heading and txt:
            cur_section = f"{path.stem} > {txt}" if not txt.startswith(path.stem) else txt
            # heading 自身也作为内容入段
            cur_text_parts.append(f"# {txt}")
            if sum(len(s) for s in cur_text_parts) > PAGE_CHAR_BUDGET:
                flush("heading_split")
        elif txt:
            cur_text_parts.append(txt)
            if sum(len(s) for s in cur_text_parts) > PAGE_CHAR_BUDGET:
                flush("char_budget")

    # 表格(追加到最后一页)
    if doc.tables:
        table_blocks = []
        for tbl in doc.tables:
            t = _table_to_text(tbl)
            if t:
                table_blocks.append(t)
        if table_blocks:
            cur_text_parts.append("\n".join(table_blocks))

    flush("end")
    if not pages:
        # 空文档也给一个占位页
        pages.append(Page(page_no=1, text="", section_path=path.stem))
    return pages


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    pages = parse_docx(p)
    print(f"parsed {len(pages)} pages from {p.name}")
    for pg in pages[:3]:
        print(f"\n--- page {pg.page_no} section={pg.section_path} ---")
        print(pg.text[:300])
