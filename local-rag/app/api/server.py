"""FastAPI 主入口"""
import os
import time
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db.database import init_db, get_conn
from app.auth.security import (
    login as auth_login,
    get_current_user,
    require_role,
    check_doc_access,
)
from app.core.config import DATA_DIR, OBJECT_STORE_DIR
from app.core.trace import stage, log, new_trace_id
from app.ingest.parser import SUPPORTED_SUFFIXES
from app.ingest.pipeline import ingest_file, reingest_version
from app.ingest.synthesizer import synthesize
from app.retrieval.hybrid import hybrid_search
from app.retrieval.embedder import count as milvus_count, ensure_collection
from app.retrieval import bm25_index


app = FastAPI(title="Local RAG", version="0.1.0")


# 对象存储静态路由(图片等二进制)
app.mount("/files", StaticFiles(directory=str(OBJECT_STORE_DIR)), name="files")


@app.on_event("startup")
def startup():
    init_db()
    # 提前建/校验 Milvus collection schema(支持 MILVUS_RESET=1 重置)
    reset = os.getenv("MILVUS_RESET", "0") == "1"
    ensure_collection(reset=reset)
    print(f"[startup] DB initialized, Milvus collection {'rebuilt' if reset else 'ready'}")


# ---- 鉴权 ----
class LoginReq(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
def api_login(req: LoginReq):
    res = auth_login(req.username, req.password)
    if not res:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return res


@app.get("/api/auth/me")
def api_me(user: dict = Depends(get_current_user)):
    return user


# ---- 文档摄入 ----
@app.post("/api/ingest")
async def api_ingest(
    file: UploadFile = File(...),
    title: str = Form(...),
    business_hint: Optional[str] = Form(None),
    change_note: Optional[str] = Form(None),
    user: dict = Depends(require_role("admin", "editor")),
):
    """上传并摄入文档"""
    if not file or not file.filename:
        raise HTTPException(400, "file is required")

    # 后缀预检
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            400,
            f"unsupported file type: {suffix} "
            f"(supported: {', '.join(sorted(SUPPORTED_SUFFIXES))})"
        )

    tmp_path = DATA_DIR / f"_upload_{file.filename}"
    try:
        with open(tmp_path, "wb") as f:
            f.write(await file.read())
    except Exception as e:
        raise HTTPException(400, f"save upload failed: {e}")
    # 给这次摄入分配一个 trace_id,贯穿整条 pipeline
    trace_id = new_trace_id()
    log(trace_id, "api", "ingest_receive",
        filename=file.filename, size_bytes=tmp_path.stat().st_size,
        user_id=user["id"], title=title)
    try:
        report = ingest_file(tmp_path, title, user["id"], business_hint, change_note,
                             trace_id=trace_id)
    except FileNotFoundError as e:
        raise HTTPException(400, f"file not found: {e}")
    except ValueError as e:
        raise HTTPException(400, f"invalid file: {e}")
    except Exception as e:
        # 记录到日志,返通用 500 + 类型提示
        import traceback
        traceback.print_exc()
        raise HTTPException(
            500,
            f"ingest failed ({type(e).__name__}): {str(e)[:200]}"
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return report


@app.post("/api/documents/{doc_id}/reingest/{version_id}")
def api_reingest(
    doc_id: int, version_id: int,
    user: dict = Depends(require_role("admin", "editor")),
):
    if not check_doc_access(user, doc_id, "write"):
        raise HTTPException(403, "no write access")
    return reingest_version(doc_id, version_id, user["id"])


# ---- 文档 / 版本管理 ----
@app.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user)):
    """列出当前用户可见的文档"""
    with get_conn() as conn:
        if user["role"] == "admin":
            rows = conn.execute(
                """SELECT d.*, u.username as owner_name FROM documents d
                   JOIN users u ON u.id=d.uploaded_by ORDER BY d.updated_at DESC"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT d.*, u.username as owner_name FROM documents d
                   JOIN users u ON u.id=d.uploaded_by
                   JOIN permissions p ON p.document_id=d.id
                   WHERE p.user_id=? ORDER BY d.updated_at DESC""",
                (user["id"],),
            ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/documents/{doc_id}/versions")
def list_versions(doc_id: int, user: dict = Depends(get_current_user)):
    if not check_doc_access(user, doc_id, "read"):
        raise HTTPException(403, "no read access")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT v.*, u.username as author_name FROM versions v
               JOIN users u ON u.id=v.created_by
               WHERE v.document_id=? ORDER BY v.version_no DESC""",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/documents/{doc_id}/rollback/{version_no}")
def rollback(doc_id: int, version_no: int, user: dict = Depends(require_role("admin"))):
    """回滚:把 current_version 改成指定 version_no"""
    with get_conn() as conn:
        ver = conn.execute(
            "SELECT id FROM versions WHERE document_id=? AND version_no=?",
            (doc_id, version_no),
        ).fetchone()
        if not ver:
            raise HTTPException(404, "version not found")
        conn.execute(
            "UPDATE documents SET current_version=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (version_no, doc_id),
        )
    return {"doc_id": doc_id, "current_version": version_no}


# ---- 权限管理 ----
class PermReq(BaseModel):
    user_id: int
    document_id: int
    permission: str  # read / write / owner

@app.post("/api/permissions")
def grant_permission(req: PermReq, user: dict = Depends(require_role("admin"))):
    if req.permission not in ("read", "write", "owner"):
        raise HTTPException(400, "permission must be read/write/owner")
    with get_conn() as conn:
        # upsert
        conn.execute(
            """INSERT INTO permissions (user_id, document_id, permission, granted_by)
               VALUES (?,?,?,?)
               ON CONFLICT(user_id, document_id) DO UPDATE SET
                 permission=excluded.permission, granted_by=excluded.granted_by,
                 granted_at=CURRENT_TIMESTAMP""",
            (req.user_id, req.document_id, req.permission, user["id"]),
        )
    return {"ok": True}


@app.get("/api/permissions/{doc_id}")
def list_permissions(doc_id: int, user: dict = Depends(require_role("admin"))):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.*, u.username FROM permissions p
               JOIN users u ON u.id=p.user_id WHERE p.document_id=?""",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- 查询 / 检索 ----
class QueryReq(BaseModel):
    query: str
    top_k: int = 5
    use_bm25: bool = True
    use_vector: bool = True
    use_keyword: bool = True
    document_ids: Optional[List[int]] = None
    category: Optional[str] = None  # 业务分类过滤

@app.post("/api/query")
def api_query(req: QueryReq, user: dict = Depends(get_current_user)):
    """混合检索 + LLM 总结"""
    t0 = time.time()
    trace_id = new_trace_id()
    log(trace_id, "query", "receive",
        query=req.query, user_id=user["id"], role=user["role"],
        top_k=req.top_k,
        flags=f"bm25={req.use_bm25} vector={req.use_vector} kw={req.use_keyword}",
        category=req.category or "")

    # 0. 简单改写:把 query 标准化(去末尾标点、空格),当改写词记录
    rewrite = req.query.strip().rstrip("。！？?!.,，;；:：")
    if rewrite != req.query:
        log(trace_id, "query", "rewrite",
            original=req.query, rewritten=rewrite)

    # 1. 收集用户可见文档
    with get_conn() as conn:
        if user["role"] == "admin":
            visible_ids = [r["id"] for r in conn.execute("SELECT id FROM documents").fetchall()]
        else:
            visible_ids = [r["id"] for r in conn.execute(
                "SELECT document_id as id FROM permissions WHERE user_id=?", (user["id"],),
            ).fetchall()]
    log(trace_id, "query", "visible_docs", count=len(visible_ids))

    if not visible_ids:
        log(trace_id, "query", "no_visible_docs")
        return {"results": [], "answer": "暂无可访问的文档", "sources": [],
                "latency_ms": 0, "trace_id": trace_id, "visible_docs": 0}

    # 2. 限定到 req 指定的
    target_ids = req.document_ids or visible_ids
    target_ids = [d for d in target_ids if d in visible_ids]
    log(trace_id, "query", "scope", visible=len(visible_ids),
        requested=len(req.document_ids) if req.document_ids else 0,
        effective=len(target_ids))

    if not target_ids:
        log(trace_id, "query", "no_effective_docs")
        return {"results": [], "answer": "所选文档无访问权限", "sources": [],
                "latency_ms": 0, "trace_id": trace_id, "visible_docs": len(visible_ids)}

    # 3. 跑混合检索
    log(trace_id, "query", "retrieval_start",
        paths=[p for p, on in [("bm25", req.use_bm25),
                                ("vector", req.use_vector),
                                ("keyword", req.use_keyword)] if on])
    with stage(trace_id, "hybrid_search"):
        search_result = hybrid_search(
            req.query, document_ids=target_ids, top_k=req.top_k,
            use_bm25=req.use_bm25, use_vector=req.use_vector, use_keyword=req.use_keyword,
        )
    hits = search_result["hits"]
    rtrace = search_result["trace"]

    # 各路径召回详情
    log(trace_id, "retrieval", "bm25_hits",
        count=len(rtrace["bm25"]),
        top=rtrace["bm25"][:5])
    log(trace_id, "retrieval", "vector_hits",
        model=rtrace["models"]["vector"],
        count=len(rtrace["vector"]),
        top=rtrace["vector"][:5])
    log(trace_id, "retrieval", "keyword_hits",
        count=len(rtrace["keyword"]),
        top=rtrace["keyword"][:5])

    # 4. RRF 融合
    log(trace_id, "rerank", "rrf_fusion",
        model=rtrace["models"]["rerank"],
        candidates=len(rtrace["candidates"]),
        top=rtrace["candidates"][:5])

    # 5. 业务分类过滤(在 RRF 之后,这样过滤后的 top_k 还能看)
    if req.category:
        before = len(hits)
        hits = [r for r in hits if r.get("category") == req.category]
        log(trace_id, "query", "category_filter",
            filter=req.category, before=before, after=len(hits))

    # 6. LLM 总结
    log(trace_id, "summarize", "start",
        model_candidate=os.getenv("LLM_MODEL", "(env not set)"),
        context_chunks=len(hits))
    with stage(trace_id, "llm_summarize"):
        synth = synthesize(req.query, hits)
    log(trace_id, "summarize", "done",
        model=synth.get("model"),
        fallback=synth.get("fallback", False),
        answer_len=len(synth.get("answer", "")),
        sources=len(synth.get("sources", [])))

    latency = int((time.time() - t0) * 1000)
    log(trace_id, "query", "done",
        total_ms=latency,
        result_count=len(hits))

    # 7. 记 SQLite 日志(沿用 query_logs 表)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO query_logs (user_id, query, result_count, latency_ms) VALUES (?,?,?,?)",
            (user["id"], req.query, len(hits), latency),
        )

    return {
        "results": hits,
        "answer": synth.get("answer", ""),
        "sources": synth.get("sources", []),
        "answer_meta": {
            "model": synth.get("model"),
            "fallback": synth.get("fallback", False),
        },
        "retrieval_trace": {
            "bm25_count": len(rtrace["bm25"]),
            "vector_count": len(rtrace["vector"]),
            "vector_model": rtrace["models"]["vector"],
            "rerank_model": rtrace["models"]["rerank"],
            "keyword_count": len(rtrace["keyword"]),
            "bm25_top": rtrace["bm25"][:3],
            "vector_top": rtrace["vector"][:3],
        },
        "latency_ms": latency,
        "visible_docs": len(visible_ids),
        "trace_id": trace_id,
    }


# ---- 统计 / 状态 ----
@app.get("/api/stats")
def stats(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        doc_count = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        ver_count = conn.execute("SELECT COUNT(*) c FROM versions").fetchone()["c"]
        chunk_count = conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
        user_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        query_count = conn.execute("SELECT COUNT(*) c FROM query_logs").fetchone()["c"]
        by_cat = conn.execute(
            "SELECT business_category, COUNT(*) c FROM documents GROUP BY business_category"
        ).fetchall()
    return {
        "documents": doc_count,
        "versions": ver_count,
        "chunks": chunk_count,
        "users": user_count,
        "queries": query_count,
        "milvus_vectors": milvus_count(),
        "bm25_indexes": bm25_index.total_indexes(),
        "by_category": [dict(r) for r in by_cat],
    }


# ---- 最简 HTML 上传页 ----
INDEX_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Local RAG</title>
<style>
body{font-family:-apple-system,sans-serif;max-width:880px;margin:30px auto;padding:0 20px;color:#222}
h1{font-size:22px;border-bottom:1px solid #eee;padding-bottom:8px}
.card{background:#f6f8fa;padding:14px 18px;border-radius:8px;margin:14px 0}
input,button,select{padding:6px 10px;margin:4px 0;font-size:14px}
button{background:#2563eb;color:#fff;border:0;border-radius:4px;cursor:pointer}
pre{background:#0d1117;color:#c9d1d9;padding:12px;border-radius:6px;overflow:auto;font-size:12px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
label{font-size:13px;color:#666}
</style></head><body>
<h1>Local RAG 上传 & 查询</h1>

<div class="card">
<h3>1. 登录拿 token</h3>
<div class="row">
<input id="u" placeholder="username" value="admin">
<input id="p" type="password" placeholder="password" value="admin123">
<button onclick="doLogin()">登录</button>
<span id="loginStatus"></span>
</div></div>

<div class="card">
<h3>2. 上传文档</h3>
<div class="row">
<input id="title" placeholder="文档标题" value="测试文档">
<input id="cat" placeholder="业务分类(可选)" value="">
<input id="note" placeholder="变更说明(可选)" value="">
</div>
<input type="file" id="file">
<button onclick="doUpload()">上传并摄入</button>
<pre id="uploadResult"></pre></div>

<div class="card">
<h3>3. 查询</h3>
<div class="row">
<input id="q" placeholder="搜索关键词" style="flex:1" value="">
<button onclick="doQuery()">查询</button>
</div>
<label><input type="checkbox" id="useBm25" checked> BM25</label>
<label><input type="checkbox" id="useVec" checked> 向量</label>
<label><input type="checkbox" id="useKw" checked> 关键词</label>
<pre id="queryResult"></pre></div>

<div class="card">
<h3>4. 系统状态</h3>
<button onclick="doStats()">刷新状态</button>
<pre id="stats"></pre></div>

<script>
let TOKEN = localStorage.getItem('rag_token') || '';

async function req(path, opts={}) {
  opts.headers = Object.assign({'Content-Type':'application/json'}, opts.headers||{});
  if (TOKEN) opts.headers['Authorization'] = 'Bearer '+TOKEN;
  const r = await fetch(path, opts);
  const t = await r.text();
  try { return JSON.parse(t); } catch { return t; }
}

async function doLogin() {
  const r = await req('/api/auth/login', {method:'POST', body: JSON.stringify({
    username: document.getElementById('u').value, password: document.getElementById('p').value})});
  if (r.token) { TOKEN = r.token; localStorage.setItem('rag_token', TOKEN);
    document.getElementById('loginStatus').innerText = '✓ '+r.user.username+' / '+r.user.role; }
  else document.getElementById('loginStatus').innerText = '✗ '+JSON.stringify(r);
}

async function doUpload() {
  const f = document.getElementById('file').files[0]; if (!f) return alert('选文件');
  const fd = new FormData();
  fd.append('file', f);
  fd.append('title', document.getElementById('title').value);
  fd.append('business_hint', document.getElementById('cat').value);
  fd.append('change_note', document.getElementById('note').value);
  const r = await fetch('/api/ingest', {method:'POST', body: fd,
    headers: {'Authorization': 'Bearer '+TOKEN}});
  const out = document.getElementById('uploadResult');
  if (r.ok) {
    out.innerText = '✓ ' + (await r.text());
    out.style.color = '#0a0';
  } else {
    const err = await r.text();
    out.innerText = `✗ [${r.status}] ${err}`;
    out.style.color = '#c00';
  }
  doStats();
}

async function doQuery() {
  const r = await req('/api/query', {method:'POST', body: JSON.stringify({
    query: document.getElementById('q').value, top_k: 5,
    use_bm25: document.getElementById('useBm25').checked,
    use_vector: document.getElementById('useVec').checked,
    use_keyword: document.getElementById('useKw').checked})});
  document.getElementById('queryResult').innerText = JSON.stringify(r, null, 2);
}

async function doStats() {
  const r = await req('/api/stats');
  document.getElementById('stats').innerText = JSON.stringify(r, null, 2);
}
doStats();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML