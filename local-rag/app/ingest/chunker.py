"""
语意切分:基于 LangChain RecursiveCharacterTextSplitter,中文友好

输入: Page dataclass (或纯文本,向后兼容)
输出: [{text, page, chunk_index, doc_title, section_path, image_id, image_caption, image_url}]
"""
import sys
from typing import List

# pyarrow 19+ 把 PyExtensionType 改名为 ExtensionType
# datasets 库还在用旧名 → 加载 sentence_transformers → 加载 datasets → 崩
# 在最早期 monkey-patch 一下
try:
    import pyarrow as _pa
    if not hasattr(_pa, "PyExtensionType"):
        _pa.PyExtensionType = _pa.ExtensionType
except ImportError:
    pass

from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.config import CHUNK_SIZE, CHUNK_OVERLAP


ZH_SEPARATORS = [
    "\n\n", "\n",
    "。", "！", "？", "；", "：", "，",
    ". ", "! ", "? ", "; ", ": ", ",",
    " ", "",
]


_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=ZH_SEPARATORS,
    length_function=len,
    is_separator_regex=False,
    keep_separator=True,
)


def semantic_chunk(text: str, page_label: str = "") -> List[dict]:
    """
    旧接口:纯文本切分,返回 [{text, page, chunk_index}]
    保留以兼容 pipeline 历史路径
    """
    if not text or not text.strip():
        return []
    raw = _SPLITTER.split_text(text)
    return [
        {"text": t, "page": page_label, "chunk_index": i}
        for i, t in enumerate(raw) if t.strip()
    ]


def chunk_page(page, doc_title: str = "") -> List[dict]:
    """
    新接口:接 Page dataclass, 返回结构化 chunk 列表
    每个 chunk 带 doc_title / section_path / page_no,方便检索回带
    """
    if not page.text or not page.text.strip():
        return []
    raw_chunks = _SPLITTER.split_text(page.text)
    section_path = page.section_path or ""
    page_label = str(page.page_no)
    chunks = []
    for i, txt in enumerate(raw_chunks):
        if not txt.strip():
            continue
        chunks.append({
            "text": txt,
            "page": page_label,
            "page_no": page.page_no,
            "chunk_index": i,
            "doc_title": doc_title,
            "section_path": section_path,
            "image_id": None,
            "image_caption": None,
            "image_url": None,
        })
    return chunks


if __name__ == "__main__":
    from app.ingest.parser_pdf import Page
    sample_page = Page(
        page_no=1,
        text="""人工智能在金融行业的应用日益广泛。从智能风控到智能投顾,AI 正在重塑金融业态。

机器学习模型能够处理海量交易数据,识别异常模式。深度学习则在图像识别、自然语言处理等领域表现突出。

然而,AI 在金融领域的应用也面临挑战。数据隐私、模型可解释性、监管合规等问题需要持续关注。

未来,联邦学习、可解释 AI 等新技术有望缓解这些问题。""",
        section_path="第3章 AI > 3.2 金融",
    )
    cs = chunk_page(sample_page, doc_title="2024 金融科技报告.pdf")
    for c in cs:
        print(f"\n[{c['chunk_index']}] doc={c['doc_title']} sec={c['section_path']} p={c['page_no']} len={len(c['text'])}")
        print(c["text"])
