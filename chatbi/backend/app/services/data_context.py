"""Database schema and metric definitions — provides context for LLM SQL generation."""

import aiosqlite
from pathlib import Path
from typing import Any


SCHEMA_DESCRIPTION = """
数据库包含电商零售数据，3张表：

1. products（产品表）
   - product_id: 产品ID
   - product_name: 产品名称
   - category: 产品类别（电子产品/服装/家居/食品/运动）
   - price: 单价（元）
   - created_at: 上架时间

2. customers（客户表）
   - customer_id: 客户ID
   - customer_name: 客户名称（公司名或个人名）
   - segment: 客户类型（企业客户/个人消费/小企业）
   - city: 城市
   - region: 地区（华北/华东/华南/华中/西南/西北/东北）
   - registered_at: 注册时间

3. orders（订单表）
   - order_id: 订单ID
   - customer_id: 客户ID（关联customers）
   - product_id: 产品ID（关联products）
   - quantity: 购买数量
   - unit_price: 成交单价（元）
   - total_amount: 总金额（元）= unit_price * quantity
   - order_date: 订单日期（YYYY-MM-DD）
   - region: 地区
   - payment_method: 支付方式（微信支付/支付宝/银行转账/信用卡/企业对公）
   - status: 状态（completed/refunded/processing）

SQL规则：
- 只允许SELECT查询，禁止INSERT/UPDATE/DELETE/DROP
- 日期间过滤用 order_date BETWEEN 'start' AND 'end'
- 金额聚合用 SUM(total_amount)
- 计数用 COUNT(DISTINCT ...)
- TOP N 用 LIMIT
- 分组用 GROUP BY
- 日期截断到月用 strftime('%Y-%m', order_date)

常见指标查询模式：
- "总销售额" → SELECT SUM(total_amount) FROM orders WHERE status='completed'
- "各品类销售额" → SELECT p.category, SUM(o.total_amount) FROM orders o JOIN products p ...
- "月趋势" → SELECT strftime('%Y-%m', order_date) as month, SUM(total_amount) ...
- "地区对比" → SELECT region, SUM(total_amount) ...
- "TOP产品" → SELECT p.product_name, SUM(o.total_amount) ... GROUP BY ... ORDER BY ... DESC LIMIT 10
- "客户分析" → SELECT c.segment, COUNT(DISTINCT o.customer_id) ...
- "季度同比" → 按季度GROUP BY，比较不同年份
"""

FEW_SHOT_EXAMPLES = """
示例1：
问：上个月总销售额是多少？
答：SELECT SUM(total_amount) FROM orders WHERE status='completed' AND order_date >= date('now', '-1 month', 'start of month') AND order_date < date('now', 'start of month')

示例2：
问：各品类销量排名
答：SELECT p.category, COUNT(*) as order_count, SUM(o.total_amount) as total_revenue FROM orders o JOIN products p ON o.product_id = p.product_id WHERE o.status='completed' GROUP BY p.category ORDER BY total_revenue DESC

示例3：
问：华东地区卖得最好的5个产品
答：SELECT p.product_name, p.category, SUM(o.total_amount) as revenue FROM orders o JOIN products p ON o.product_id = p.product_id WHERE o.region='华东' AND o.status='completed' GROUP BY p.product_name ORDER BY revenue DESC LIMIT 5

示例4：
问：2024年每个季度的销售额趋势
答：SELECT strftime('%Y-Q', order_date) || CAST((CAST(strftime('%m', order_date) AS INTEGER) - 1) / 3 + 1 AS TEXT) as quarter, SUM(total_amount) as revenue FROM orders WHERE status='completed' AND order_date BETWEEN '2024-01-01' AND '2024-12-31' GROUP BY quarter ORDER BY quarter

示例5：
问：企业客户消费最多的产品品类
答：SELECT p.category, SUM(o.total_amount) as revenue, COUNT(DISTINCT o.customer_id) as buyers FROM orders o JOIN products p ON o.product_id = p.product_id JOIN customers c ON o.customer_id = c.customer_id WHERE c.segment='企业客户' AND o.status='completed' GROUP BY p.category ORDER BY revenue DESC
"""

SYSTEM_PROMPT = """你是一个专业的SQL数据分析助手。根据用户的自然语言问题，生成对应的SQL查询语句。

## 数据库Schema
{SCHEMA}

## SQL生成规则:
1. 只生成SELECT查询语句 — 绝对不允许INSERT/UPDATE/DELETE/DROP/ALTER
2. 表名和列名必须严格匹配Schema定义（注意是英文表名列名）
3. 如果问题不明确，选择最合理的解释
4. 总是使用聚合函数（SUM/COUNT/AVG）配合GROUP BY
5. 时间范围查询优先使用BETWEEN，日期格式为'YYYY-MM-DD'
6. 金额单位是元(RMB)，保留2位小数用ROUND(xxx, 2)
7. TOP N 用 LIMIT
8. 查询完成后，用中文给出数据解读
9. 如果问题不是数据查询类（比如闲聊），请礼貌地引导用户提出数据问题

## 返回格式
你必须返回JSON格式（不要markdown代码块）:
```json
{{
  "sql": "生成的SQL语句",
  "explanation": "对查询逻辑的中文解释",
  "visualization": "建议的图表类型: bar(柱状比较), line(趋势), pie(占比), table(表格), 如果不适合图表则填null"
}}
```

## 参考示例
{FEW_SHOT}
"""


async def get_db_schema(db_path: str) -> list[dict[str, Any]]:
    """Get detailed schema from the actual database (async)."""
    conn = await aiosqlite.connect(db_path)
    cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    rows = await cursor.fetchall()
    tables = []
    for (tname,) in rows:
        cols = await (await conn.execute(f"PRAGMA table_info({tname})")).fetchall()
        col_info = [{"name": c[1], "type": c[2], "notnull": bool(c[3])} for c in cols]
        count_row = await (await conn.execute(f"SELECT COUNT(*) FROM {tname}")).fetchone()
        count = count_row[0] if count_row else 0
        tables.append({"name": tname, "columns": col_info, "row_count": count})
    await conn.close()
    return tables


def get_metric_recommendations() -> list[dict[str, str]]:
    """Return common metric suggestions for the frontend."""
    return [
        {"question": "总销售额是多少？", "category": "概览"},
        {"question": "各品类销售额排名", "category": "概览"},
        {"question": "最近一个月的销售趋势", "category": "时间"},
        {"question": "各地区的销售额对比", "category": "地域"},
        {"question": "卖得最好的10个产品", "category": "产品"},
        {"question": "各类客户消费能力对比", "category": "客户"},
        {"question": "2024年各季度销售额", "category": "时间"},
        {"question": "各支付方式使用占比", "category": "概览"},
        {"question": "退货率最高的产品", "category": "产品"},
        {"question": "华北地区企业客户最爱买什么", "category": "地域"},
    ]


async def build_extended_schema_description(db_path: str) -> str:
    """Combine the static SCHEMA_DESCRIPTION with uploaded table schemas."""
    from .excel_import import get_uploaded_tables_schema

    uploaded = await get_uploaded_tables_schema(db_path)
    if uploaded:
        return SCHEMA_DESCRIPTION.rstrip() + "\n" + uploaded
    return SCHEMA_DESCRIPTION
