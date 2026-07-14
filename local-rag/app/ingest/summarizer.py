"""摘要:截取前 N 句 + 关键词高频(可后续接 LLM 改写)"""
import re
import jieba
from collections import Counter
from typing import List


def _stopwords() -> set:
    # 极简停用词
    return {
        "的", "了", "是", "在", "和", "与", "及", "或", "为", "对", "也", "都", "就",
        "将", "可", "能", "有", "无", "由", "从", "到", "以", "按", "对", "本", "此",
        "等", "中", "上", "下", "并", "或", "而", "但", "如", "若", "所", "其", "该",
    }


def summarize(text: str, top_sent: int = 2, max_chars: int = 120) -> str:
    """抽取式摘要:选最关键的 top_sent 句"""
    if not text:
        return ""
    sents = re.split(r'(?<=[。！？!?\.])\s*', text.replace("\n", " "))
    sents = [s.strip() for s in sents if s.strip() and len(s.strip()) > 4]
    if not sents:
        return text[:max_chars]
    if len(sents) <= top_sent:
        summary = "。".join(sents)
        return summary[:max_chars] + ("。" if not summary.endswith("。") else "")

    # 句向量:词频
    sw = _stopwords()
    word_freq = Counter()
    for s in sents:
        for w in jieba.cut(s):
            w = w.strip().lower()
            if w and w not in sw and len(w) > 1:
                word_freq[w] += 1

    # 句得分:句子词频之和 / 长度(归一)
    scored = []
    for i, s in enumerate(sents):
        words = [w for w in jieba.cut(s) if w.strip() and w not in sw and len(w) > 1]
        score = sum(word_freq.get(w, 0) for w in words) / max(len(words), 1)
        scored.append((score, i, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = sorted(scored[:top_sent], key=lambda x: x[1])
    summary = "。".join(s for _, _, s in picked)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "..."
    return summary


if __name__ == "__main__":
    t = "人工智能在金融行业的应用日益广泛。从智能风控到智能投顾,AI 正在重塑金融业态。机器学习模型能够处理海量交易数据,识别异常模式。深度学习则在图像识别、自然语言处理等领域表现突出。然而,AI 在金融领域的应用也面临挑战。数据隐私、模型可解释性、监管合规等问题需要持续关注。"
    print(summarize(t, top_sent=2))