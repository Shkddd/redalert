# RedAlert — 个人项目合集

游戏 + AI/ML 项目，统一存放。

---

## 游戏

| 文件 | 说明 |
|------|------|
| `index.html` | 红色警戒风格 RTS 游戏 |
| `mario.html` | 超级马里奥风格平台跳跃 |
| `mario-mobile.html` | 手机适配版自动跑酷 |

双击 HTML 文件直接开玩，无外部依赖。

---

## AI / ML 项目

### local-rag — RAG 知识库

FastAPI + Milvus Lite + SQLite + BGE 向量检索。支持多格式文档摄入（PDF/DOCX/XLSX/CSV/TXT/图片），混合检索（向量 + BM25），版本管理。

```
cd local-rag
pip install -r requirements.txt
python3 -m uvicorn app.main:app --port 8000
```

### local-agent — 多框架 Agent 对比

4 种 Agent 框架实现对比：v1 手写 ReAct / v2 LangGraph / v3 AutoGen / v4 LangChain。FastAPI 服务 + 可观测性。

```
cd local-agent
pip install -r requirements.txt
python3 -m uvicorn app.api.server:app --port 8001
```

### chatbi — 自然语言转 SQL

LLM 驱动的 ChatBI 系统，自然语言查询 → SQL → 图表。FastAPI + SQLite，前端 Chart.js 可视化。

```
cd chatbi
cp backend/.env.example backend/.env  # 填入 LLM API Key
pip install -r backend/requirements.txt
cd backend && python3 -m uvicorn app.main:app --port 8000
```

### contract-review — AI 合同审查

上传合同文档，AI 自动标注风险条款、生成审查报告。FastAPI + 向量知识库。

```
cd contract-review
cp backend/.env.example backend/.env  # 填入 LLM API Key
pip install -r backend/requirements.txt
cd backend && python3 -m uvicorn app.main:app --port 8000
```

### nanoGPT — GPT 训练实验

Karpathy nanoGPT fork，用于小规模 GPT 训练实验（莎士比亚、QA、法律文本等）。

```
cd nanoGPT
pip install -r requirements.txt  # 或 pyproject.toml
python train.py config/train_shakespeare_char.py
```

### SmallVIT — 轻量多模态模型

轻量级 Vision-Language 模型训练，支持文生图和多模态理解。

```
cd SmallVIT
python train_multimodal.py
```

---

## 目录结构

```
redalert/
├── index.html              # 红警 RTS
├── mario.html              # 马里奥
├── mario-mobile.html       # 马里奥手机版
├── local-rag/              # RAG 知识库
├── local-agent/            # Agent 框架对比
├── chatbi/                 # 自然语言转 SQL
├── contract-review/        # AI 合同审查
├── nanoGPT/                # GPT 训练
└── SmallVIT/               # 轻量多模态
```
