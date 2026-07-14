# ContractReview — 合同智能审核平台

上传 PDF/Word 合同，基于知识库（传统条款库 + 向量库混合搜索）进行智能比对，输出带**原生注释气泡**的批注版合同。

## 核心功能

- **📄 文档上传** — 支持 PDF、DOCX 格式，自动提取文本并拆分为条款
- **📚 知识库管理** — 维护标准条款库（分类/标签/风险等级），支持增删改查
- **🧠 向量知识库** — 导入外部文档/网页作为参考知识，自动分块 + 向量化存储
- **🔍 混合搜索** — RRF 融合向量语义搜索 + 纯 Python BM25 关键词搜索，审核时同时参考传统知识库与向量库
- **🤖 智能审核** — 批量比对合同条款与知识库，LLM 驱动差异分析与风险识别
- **✅ 审核报告** — 可视化风险总览 + 逐条批注详情（匹配/冲突/缺失）
- **💬 原生注释导出** — 下载带批注的 PDF/DOCX，批注以原生注释气泡呈现（鼠标悬停/点击查看全文）
- **⚡ 批量分析** — 所有条款一次性发送 LLM，避免逐条串行调用

## 项目结构

```
contract-review/
├── backend/
│   ├── app/
│   │   ├── config.py              # 配置管理（LLM、数据库路径）
│   │   ├── main.py                # FastAPI 入口 + 静态文件挂载
│   │   ├── models/schemas.py      # Pydantic 数据模型
│   │   ├── services/
│   │   │   ├── db.py              # SQLite 初始化 + 示例数据 + 向量库表
│   │   │   ├── document_parser.py # PDF/DOCX 文本提取与条款拆分
│   │   │   ├── knowledge_base.py  # 知识库 CRUD + 混合搜索
│   │   │   ├── kb_vector.py       # 向量库：分块/embedding/BM25/混合搜索
│   │   │   ├── annotator.py       # LLM 批量审核引擎
│   │   │   └── annotated_export.py# 批注版导出（PDF/DOCX 原生注释）
│   │   └── routers/
│   │       ├── documents.py       # 文档上传/列表/删除 API
│   │       ├── knowledge_base.py  # 知识库 CRUD + 向量库 API
│   │       └── review.py          # 审核 + 批注版下载 API
│   ├── data/uploads/              # 上传文件存储
│   └── requirements.txt
├── frontend/
│   ├── index.html                 # 主页面（三标签：文档/知识库/审核结果）
│   ├── css/style.css              # 暗色主题样式
│   └── js/app.js                  # 前端逻辑
├── scripts/
│   └── create_test_contracts.py   # 测试合同生成脚本
├── .env.example
└── .gitignore
```

## 快速启动

```bash
# 1. 配置 LLM API Key（支持 DeepSeek / OpenAI / 通义千问等 OpenAI 兼容接口）
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

# 2. 安装依赖
cd backend && pip install -r requirements.txt

# 3. 启动服务
python -m uvicorn app.main:app --port 8001 --reload

# 4. 打开浏览器
open http://localhost:8001
```

## 使用流程

1. **上传合同** → 拖拽或选择 PDF/DOCX 文件，自动解析为条款
2. **管理知识库** → 新增/编辑标准条款（已内置 10+ 条示例，含风险等级）
3. **导入参考文档** → 切换到「知识库」tab，上传 PDF/DOCX 或输入 URL 导入外部知识，自动分块向量化
4. **执行审核** → 选择文档，点击「开始审核」，LLM 同时参考传统条款库 + 向量库进行混合分析
5. **查看结果** → 风险总览卡片 + 逐条批注详情（匹配/冲突/缺失），含修改建议
6. **下载批注版** → 点击「下载批注版」，获得带原生注释的 PDF/DOCX 文件

## 批注版导出格式

| 格式 | 批注方式 | 查看方式 |
|------|---------|---------|
| **PDF** | PDF 文本注释（Comment 图标） | 点击/悬停图标弹出批注气泡 |
| **DOCX** | Word 原生注释 | 右侧边栏气泡，条款标题带风险颜色高亮 |

批注内容包含：匹配类型、风险等级、参考标准条款、AI 评语、修改建议。

## 向量知识库

| 模块 | 技术 | 说明 |
|------|------|------|
| 文本分块 | 固定大小 + overlap | 按字符切分，支持 overlap 避免信息截断 |
| Embedding | LLM Provider /embeddings API | 优先使用配置的 LLM API，无需额外服务 |
| 回退方案 | TF-IDF (numpy) | API 不可用时纯本地运算，零依赖 |
| 关键词搜索 | 纯 Python BM25 | 替代 SQLite FTS4，兼容 Python 3.9 |
| 混合搜索 | RRF (Reciprocal Rank Fusion) | 向量语义 + BM25 关键词得分融合排序 |

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + SQLite |
| 文档解析 | pypdf (PDF)、python-docx (DOCX) |
| 语义搜索 | LLM API (OpenAI 兼容接口) / TF-IDF fallback |
| 关键词搜索 | 纯 Python BM25（无外部依赖） |
| 批注导出 | fpdf2 (PDF 文本注释)、python-docx + ZIP 注入 (DOCX 原生注释) |
| 前端 | 原生 HTML/CSS/JS，暗色主题 |
| 端口 | 8001 |

## 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `LLM_BASE_URL` | LLM API 地址 | `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | API 密钥 | `sk-xxx` |
| `LLM_MODEL` | 模型名称 | `deepseek-chat` |
