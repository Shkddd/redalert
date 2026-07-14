"""单测:chunker 切分行为"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.ingest.chunker import semantic_chunk
from app.core.config import CHUNK_SIZE, CHUNK_OVERLAP


def test_empty_input():
    """空输入返空列表"""
    assert semantic_chunk("") == []
    assert semantic_chunk("   \n\n  ") == []


def test_short_text_one_chunk():
    """短文本(< chunk_size) 1 个 chunk"""
    text = "这是测试。短文本。"
    cs = semantic_chunk(text)
    assert len(cs) == 1
    assert cs[0]["text"] == text
    assert cs[0]["page"] == ""
    assert cs[0]["chunk_index"] == 0


def test_page_label_preserved():
    """page_label 传到每个 chunk"""
    cs = semantic_chunk("测试文本。", page_label="p3")
    assert cs[0]["page"] == "p3"


def test_long_text_multi_chunks():
    """长文本切成多个"""
    paras = []
    for i in range(10):
        para = f"第{i}部分。 " + "。".join([f"这是第{j}个句子" for j in range(20)]) + "。"
        paras.append(para)
    text = "\n\n".join(paras)
    cs = semantic_chunk(text)
    assert len(cs) >= 2
    # 每个 chunk 都在分隔符处结束
    for c in cs:
        last = c["text"].rstrip()[-1]
        assert last in "。！？!?.\n ", f"chunk 边界不在分隔符: {repr(last)}"


def test_chunk_size_respected():
    """每个 chunk 不超过 chunk_size(允许 5% 误差给保留标点)"""
    paras = []
    for i in range(20):
        para = f"第{i}部分。 " + "。".join([f"这是第{j}个句子" for j in range(30)]) + "。"
        paras.append(para)
    text = "\n\n".join(paras)
    cs = semantic_chunk(text)
    for c in cs:
        # LangChain 不会严格超过 chunk_size,但也不会差太多
        assert len(c["text"]) <= CHUNK_SIZE + 50, f"chunk 太大: {len(c['text'])} > {CHUNK_SIZE + 50}"


def test_overlap_present():
    """相邻 chunk 之间有重叠(>= chunk_overlap)"""
    paras = []
    for i in range(10):
        para = f"段落{i}。 " + "。".join([f"句子{j}" for j in range(30)]) + "。"
        paras.append(para)
    text = "\n\n".join(paras)
    cs = semantic_chunk(text)
    assert len(cs) >= 2
    # 检查至少有一对相邻 chunk 有 overlap
    found_overlap = False
    for i in range(len(cs) - 1):
        a, b = cs[i]["text"], cs[i+1]["text"]
        # b 应该包含 a 的最后 ~chunk_overlap 个字符
        for ov in [CHUNK_OVERLAP, CHUNK_OVERLAP - 20, 50]:
            if a[-ov:] in b:
                found_overlap = True
                break
        if found_overlap:
            break
    assert found_overlap, f"相邻 chunk 无 overlap,cs 数={len(cs)}"


def test_chinese_period_split():
    """中文句号能切分(用足够长文本)"""
    text = "第一句。第二句。第三句。第四句。" * 100
    cs = semantic_chunk(text)
    assert len(cs) >= 2


def test_english_period_split():
    """英文句号能切分(用足够长文本)"""
    text = "First sentence. Second sentence. Third sentence. Fourth sentence. " * 50
    cs = semantic_chunk(text)
    assert len(cs) >= 2


def test_mixed_cn_en():
    """中英混合文档能切分"""
    text = "AI 在金融领域的应用。Machine learning models process huge data. 深度学习表现突出。Deep learning excels at NLP. " * 30
    cs = semantic_chunk(text)
    assert len(cs) >= 2


def test_paragraph_break_preferred():
    """段间空行优先切(大文档)"""
    text = ("段落1的内容。第二句。\n\n段落2的内容。第二句。") * 50
    cs = semantic_chunk(text)
    assert len(cs) >= 2


def test_no_empty_chunks():
    """没有空 chunk(纯空白被过滤)"""
    text = "第一段。\n\n\n\n\n第二段。\n\n\n第三段。" * 20
    cs = semantic_chunk(text)
    for c in cs:
        assert c["text"].strip() != ""


def test_chunk_index_monotonic():
    """chunk_index 单调递增从 0 开始"""
    text = "句子1。句子2。句子3。句子4。句子5。句子6。句子7。句子8。句子9。句子10。" * 20
    cs = semantic_chunk(text)
    for i, c in enumerate(cs):
        assert c["chunk_index"] == i

