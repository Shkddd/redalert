"""
TXT / Markdown 解析
- utf-8 优先,gbk / latin-1 兜底
- 整文作为一个 Page;section_path = 文件名(去后缀)
- 长文按空行(\n\n)切成多个 Page
"""
from pathlib import Path
from typing import List

from app.ingest.parser_pdf import Page, _clean_text


_MAX_PAGE_CHARS = 2000


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_text(path: Path) -> List[Page]:
    path = Path(path)
    text = _read_text(path)
    text = _clean_text(text)
    if not text:
        return [Page(page_no=1, text="", section_path=path.stem)]

    # 按段落(\n\n)切页
    paragraphs = text.split("\n\n")
    pages: List[Page] = []
    cur: List[str] = []
    cur_len = 0
    page_no = 1

    def flush():
        nonlocal cur, cur_len, page_no
        joined = "\n\n".join(cur)
        if joined.strip():
            pages.append(Page(
                page_no=page_no,
                text=joined,
                section_path=path.stem,
                raw_meta={"format": "txt"},
            ))
            page_no += 1
        cur = []
        cur_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if cur_len + len(para) > _MAX_PAGE_CHARS and cur:
            flush()
        cur.append(para)
        cur_len += len(para)
    flush()
    return pages


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    pages = parse_text(p)
    print(f"parsed {len(pages)} pages from {p.name}")
    for pg in pages[:3]:
        print(f"\n--- page {pg.page_no} ---")
        print(pg.text[:200])
