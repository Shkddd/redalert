"""
多格式文档解析分发
- pdf   → parser_pdf.parse_pdf (text + images + section)
- xlsx  → excel_to_md + 结构化 Page
- docx  → parser_word
- txt/md → parser_text
- jpg/png/... → parser_image (整图作为一个 Page)
"""
from pathlib import Path
from typing import List

from app.ingest.parser_pdf import Page, parse_pdf


SUPPORTED_SUFFIXES = {
    ".pdf", ".xlsx", ".xlsm", ".docx",
    ".txt", ".md",
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif",
}


def parse(path: Path) -> List[Page]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported file type: {suffix}")

    if suffix == ".pdf":
        return parse_pdf(path, extract_images=True)

    if suffix in (".xlsx", ".xlsm"):
        from app.ingest.parser_excel import parse_excel
        return parse_excel(path)

    if suffix == ".docx":
        from app.ingest.parser_word import parse_docx
        return parse_docx(path)

    if suffix in (".txt", ".md"):
        from app.ingest.parser_text import parse_text
        return parse_text(path)

    # 图片
    from app.ingest.parser_image import parse_image
    return parse_image(path)


# ============================================================
# 旧接口兼容(给 pipeline 等用, 暂留 fallback)
# ============================================================
def parse_pdf_legacy(path: Path) -> List[dict]:
    """旧接口: [{page, text}], 仅文本"""
    pages = parse_pdf(path, extract_images=False)
    return [{"page": p.page_no, "text": p.text} for p in pages]


def parse_excel_legacy(path: Path) -> List[dict]:
    """旧接口: [{page, text}], sheet 名为 page"""
    from openpyxl import load_workbook
    pages = []
    wb = load_workbook(str(path), data_only=True, read_only=True)
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            line = " | ".join(str(c) if c is not None else "" for c in row)
            if line.strip(" |"):
                rows.append(line)
        if rows:
            from app.ingest.parser_pdf import _clean_text
            pages.append({"page": sheet_name, "text": _clean_text("\n".join(rows))})
    wb.close()
    return pages


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    pages = parse(p)
    print(f"parsed {len(pages)} pages from {p.name}")
    if pages:
        print(f"page 1: text_len={len(pages[0].text)} images={len(pages[0].images)} section={pages[0].section_path}")
