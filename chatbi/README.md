# ChatBI — 自然语言驱动数据查询

用自然语言问数据，自动生成 SQL → 执行查询 → 返回结果 + 图表。

## 快速开始

### 1. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key（支持 OpenAI 兼容 API）
# LLM_BASE_URL=https://api.deepseek.com/v1
# LLM_API_KEY=sk-xxx
# LLM_MODEL=deepseek-chat
```

### 2. 启动

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000

### 3. 用 Docker

```bash
docker compose up --build
```

## 架构

```
用户问问题 → LLM(NL→SQL) → SQLite 查询 → 结果表格 + Chart.js 图表
```

- **LLM**: 任意 OpenAI 兼容 API（DeepSeek / OpenAI / 通义千问 / 本地 ollama）
- **数据库**: SQLite，首次启动自动生成 500 条电商订单样本数据
- **前端**: 纯 HTML+CSS+JS，无框架依赖

## 数据集

内置电商零售数据（SQLite，自动填充）：

| 表 | 说明 | 行数 |
|---|------|------|
| `orders` | 订单（时间/金额/地区/支付方式） | 500 |
| `products` | 商品（品类/价格） | 50 |
| `customers` | 客户（类型/城市/地区） | 20 |

## 支持的查询类型

- **概览**: 总销售额、订单数、客单价
- **时间趋势**: 日/月/季度/年度趋势，同比环比
- **品类分析**: 各品类销售额排名、销量分布
- **地域分析**: 各地区对比、区域偏好
- **客户分析**: 不同类型客户消费行为
- **TOP N**: 最畅销产品、最大客户
- **支付分析**: 支付方式占比

## 示例查询

> "上个月总销售额是多少？"
> "各品类销售额排名"
> "2024年各季度销售趋势"
> "华东地区卖得最好的5个产品"
> "哪些产品退货率最高？"
> "企业客户和个人消费者的消费能力对比"

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 自然语言查询 → SQL + 数据 + 图表 |
| `/api/health` | GET | 健康检查 + LLM/数据库状态 |
| `/api/schema` | GET | 数据库Schema |
| `/api/metrics` | GET | 建议查询列表 |
| `/api/history/{id}` | GET/DELETE | 对话历史管理 |

### POST /api/chat

```json
{
  "message": "各品类销售额排名",
  "conversation_id": "optional"
}
```

返回：
```json
{
  "answer": "...中文解读...",
  "sql": "SELECT p.category, ...",
  "data": [...],
  "columns": ["category", "revenue"],
  "chart_type": "bar",
  "chart_data": {"labels": [...], "datasets": [...]},
  "execution_time_ms": 123
}
```

## 自定义配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | LLM API 地址 |
| `LLM_API_KEY` | — | API Key |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `SEED_DATA_SIZE` | `500` | 样本数据量 |
| `PORT` | `8000` | 端口 |
