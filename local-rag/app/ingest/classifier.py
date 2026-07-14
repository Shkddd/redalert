"""业务分类:基于关键词规则打标,不需要 LLM 也能跑(LLM 模式可后续加)"""
import re
from typing import List
from app.core.config import BUSINESS_CATEGORIES


# 关键词表(实际项目可扩/可换成 LLM 分类)
_KEYWORDS = {
    "财务": ["财务", "会计", "审计", "税务", "成本", "利润", "营收", "现金流", "凭证", "预算", "报销", "应收", "应付"],
    "人事": ["人力", "招聘", "薪酬", "绩效", "员工", "入职", "离职", "培训", "考勤", "五险一金", "劳动合同"],
    "法务": ["合同", "法律", "合规", "诉讼", "仲裁", "知识产权", "专利", "商标", "法务", "条款", "违约"],
    "技术": ["系统", "架构", "代码", "开发", "数据库", "接口", "API", "服务器", "部署", "测试", "算法"],
    "运营": ["运营", "用户", "活动", "复购", "留存", "活跃", "GMV", "订单", "履约", "客服"],
    "市场": ["市场", "营销", "品牌", "投放", "广告", "PR", "公关", "新媒体", "获客"],
    "产品": ["产品", "需求", "PRD", "功能", "用户体验", "原型", "迭代", "版本"],
}


def classify(text: str) -> str:
    """返回最匹配的业务分类。规则:命中关键词数最多者,平局取字典序前"""
    if not text:
        return "通用"
    scores = {cat: 0 for cat in BUSINESS_CATEGORIES}
    for cat, kws in _KEYWORDS.items():
        for kw in kws:
            # 出现一次 +1,次数越多权重越高但有上限
            cnt = len(re.findall(re.escape(kw), text))
            scores[cat] += min(cnt, 3)
    if not scores:
        return "通用"
    best = max(scores.values())
    if best == 0:
        return "通用"
    # 字典序取第一个最大值
    for cat in sorted(scores.keys()):
        if scores[cat] == best:
            return cat
    return "通用"


def classify_batch(texts: List[str]) -> List[str]:
    return [classify(t) for t in texts]


if __name__ == "__main__":
    samples = [
        "本公司 2024 年财务预算方案,营业收入预计增长 15%",
        "新员工入职流程及五险一金办理指引",
        "技术服务合同违约责任条款解读",
    ]
    for s in samples:
        print(f"[{classify(s)}] {s}")