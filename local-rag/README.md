# Local RAG

本地 RAG 系统：多格式文档摄入 → 切分 → 分类 → 摘要 → 向量化 → 混合检索。
FastAPI + SQLite + Milvus Lite + BM25 + BGE-small-zh + LangChain 切分器 + 视觉模型。

## 启动

```bash
cd ~/local-rag
pip install -r requirements.txt
python3 scripts/gen_samples.py            # 生成多格式测试样本
uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000 看 HTML 页面。

## 默认账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | admin（全权） |
| editor | editor123 | editor（可上传） |
| viewer | viewer123 | viewer（只读） |

## 支持的格式

| 格式 | 解析器 | 文本提取 | 图片处理 | 章节识别 |
|------|--------|----------|----------|----------|
| `.pdf` | parser_pdf (pymupdf) | ✅ | ✅ 抽图 + 视觉说明 | ✅ TOC + 字号启发 |
| `.xlsx` / `.xlsm` | parser_excel (openpyxl) | ✅ 转 Markdown | — | sheet 名作为 section |
| `.docx` | parser_word (python-docx) | ✅ | — | ✅ heading 样式 |
| `.txt` / `.md` | parser_text | ✅ utf-8/gbk | — | 文件名作为 section |
| `.jpg`/`.png`/`.bmp`/`.webp`/`.gif` | parser_image (Pillow) | ✅ 视觉说明 | ✅ 整图入库 | 文件名 |

## 核心接口

| 接口 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/auth/login` | POST | 无 | 登录拿 token |
| `/api/ingest` | POST | admin/editor | 上传任意支持格式 |
| `/files/{yyyy-mm-dd}/{uuid}.{ext}` | GET | 任意 | 对象存储(模拟 OceanBase)返回图片 |
| `/api/documents` | GET | 任意已登录 | 列可见文档 |
| `/api/documents/{id}/versions` | GET | 有读权限 | 列版本 |
| `/api/documents/{id}/rollback/{ver}` | POST | admin | 回滚 |
| `/api/documents/{id}/reingest/{ver}` | POST | 有写权限 | 重处理某版本 |
| `/api/permissions` | POST | admin | 授权 |
| `/api/permissions/{doc_id}` | GET | admin | 看授权 |
| `/api/query` | POST | 任意已登录 | 混合检索(返回 doc_title/section_path/image_*) |
| `/api/stats` | GET | 任意已登录 | 系统状态 |

## 摄入流程

```
任意格式文件
   ↓ parser (按后缀分发到 parser_pdf / parser_excel / parser_word / parser_text / parser_image)
List[Page] = [{page_no, text, images, section_path, raw_meta}, ...]
   ↓ chunker.chunk_page (LangChain RecursiveCharacterTextSplitter)
文本 chunks (~500 字符, 80 字符 overlap)
   ↓ 对每页 images: vision.describe_image → caption (失败则 fallback_caption)
   ↓ object_store.save_bytes → (image_id, url)
   ↓ 写 images 表 + 构造 "图片 chunks"(caption 作为 text)
合并 chunks
   ↓ classifier (关键词规则)
业务分类: 财务/人事/法务/...
   ↓ summarizer (抽取式)
chunk 摘要
   ↓ embedder (BGE-small-zh, 512 维)
chunk 向量
   ↓ 写 Milvus Lite (含 doc_title/section_path/image_* 字段) + 写 BM25 + 写 SQLite
可检索
```

## chunk 结构化字段(检索回带)

每个 chunk 入库时带:
- `doc_title`: 文档原始文件名/标题
- `section_path`: 章节路径(PDF 大纲 / Word heading / Excel sheet / 文件名)
- `page_no`: 页码 / sheet 序号 / "1" (txt/jpg)
- `summary`: 抽取式摘要
- `image_id` / `image_caption` / `image_url`: 仅图片 chunk 有值

## 图片处理

PDF 内的图片被 pymupdf 抽出来后:
1. **过滤小图**: < 50x50 像素视为装饰图,跳过
2. **存对象存储**: `app/storage/object_store.py`,本地目录 `data/object_store/yyyy-mm-dd/uuid.png`,URL `/files/yyyy-mm-dd/uuid.png`(可换成 S3/OSS)
3. **视觉说明**: 调 minimax-cn 视觉 API(`/v1/chat/completions` + image_url data URI),生成中文说明
4. **降级**: API 不可用时,使用占位说明 `图片(WxH,位于第 N 页)`,图片二进制照样存
5. **入 chunks 表**: caption 作为该 chunk 的 text,方便文本检索召回

## 视觉 API 配置

```bash
# .env 或环境变量
LLM_BASE_URL=https://api.minimaxi.com/v1   # 兼容 OpenAI
LLM_API_KEY=your-key-here
VISION_MODEL=MiniMax-VL-01                  # 默认值,可通过 VISION_MODEL env 覆盖
```

失败行为: vision 客户端超时/4xx → 返回 None → pipeline 用 fallback_caption 兜底,不阻塞主流程。

## 对象存储(模拟 OceanBase)

`app/storage/object_store.py` 提供 `save_bytes / save_file / get_path` 接口。
接口形状与真实对象存储 (S3 / OSS / OBS) 一致,生产部署时把内部实现替换即可,调用方无需改动。

```python
from app.storage.object_store import save_bytes
image_id, url, abs_path = save_bytes(png_bytes, mime="image/png")
# url = "/files/2024-10-15/abc123.png"
```

## Milvus schema 升级

新字段 (`doc_title / section_path / image_id / image_url`) 加到 Milvus collection。
Milvus Lite 的 collection schema 不能动态加字段,所以升级方式:

```bash
MILVUS_RESET=1 uvicorn app.main:app --port 8000   # 启动时删旧 collection 重建
```

SQLite 数据保留,Milvus 旧向量会被重新索引。

## 切分器说明

`app/ingest/chunker.py` 用 LangChain `RecursiveCharacterTextSplitter`:
- 多级分隔符:段→行→中文标点(。！？；：，)→英文标点(. ! ? ; :)→空白→字
- 边界永远在分隔符处,不会硬切到词中间
- 中文/英文/中英混合都能切
- chunk_size=500, chunk_overlap=80

## 跑测试

```bash
cd ~/local-rag
/usr/local/bin/python3 -m pytest tests/ -v
```

## 混合检索

- **BM25** (rank_bm25) — 每个版本一个索引
- **向量** (Milvus Lite, IP) — 余弦相似
- **关键词** — 命中 query 字符片段
- **融合** — RRF (k=60),向量权重 1.2 / BM25 1.0 / 关键词 0.5

返回字段包括 `doc_title / section_path / image_id / image_url`,前端可直接渲染来源 + 图片。

## 版本管理

- 同一文件 hash 重复上传 → 自动 +1 version
- 每次摄入建 versions 行,可回滚 / 重处理
- 权限独立于版本(按 document 控)

## 权限

三角色 + 文档级 ACL:
- admin: 全权
- editor: 可上传,需 admin 授权具体文档
- viewer: 只读被授权文档

## 目录结构

```
~/local-rag/
├── app/
│   ├── api/server.py            # FastAPI 入口 (含 /files 静态路由)
│   ├── auth/security.py         # JWT + RBAC
│   ├── core/config.py           # 配置
│   ├── db/database.py           # SQLite (含 images 表)
│   ├── ingest/
│   │   ├── parser.py            # 多格式分发
│   │   ├── parser_pdf.py        # PDF (text + images + section)
│   │   ├── parser_excel.py      # Excel → Markdown
│   │   ├── parser_word.py       # .docx
│   │   ├── parser_text.py       # .txt/.md
│   │   ├── parser_image.py      # 单图文件
│   │   ├── chunker.py           # 语意切分
│   │   ├── classifier.py        # 业务分类
│   │   ├── summarizer.py        # 摘要
│   │   ├── vision.py            # 视觉 API 客户端
│   │   └── pipeline.py          # 完整摄入
│   ├── storage/
│   │   └── object_store.py      # 模拟 OceanBase 对象存储
│   └── retrieval/
│       ├── embedder.py          # BGE + Milvus (含新字段 schema)
│       ├── bm25_index.py        # BM25
│       └── hybrid.py            # 混合检索
├── data/
│   ├── rag.db                   # SQLite
│   ├── rag_milvus.db            # Milvus Lite
│   ├── uploads/                 # 原始文件
│   ├── versions/                # 版本快照
│   └── object_store/            # 图片二进制(模拟 OceanBase)
├── scripts/
│   └── gen_samples.py           # 多格式样本生成
└── requirements.txt
```
