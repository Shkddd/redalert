"""技能注册中心:每个技能是一个 Python 函数 + JSON schema"""
import os
import json
import subprocess
import shlex
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, List, Any
from app.core.config import RAG_BASE_URL


# ============================================================
# 技能实现
# ============================================================

def read_file(path: str, max_chars: int = 5000) -> Dict:
    """读文件,带行号截断。max_chars 是返回 text 的上限(包含截断提示)"""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"file not found: {p}"}
    if p.is_dir():
        return {"error": f"is a directory: {p}", "entries": sorted(os.listdir(p))[:50]}
    try:
        text = p.read_text(errors="replace")
        truncated = False
        # 给 truncated 提示预留 ~40 字符
        if len(text) > max_chars:
            keep = max(0, max_chars - 40)
            text = text[:keep] + f"\n... [truncated, total {len(text)} chars]"
            truncated = True
        return {"path": str(p), "size": p.stat().st_size, "text": text, "truncated": truncated}
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str, mode: str = "w") -> Dict:
    """写文件"""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode in ("a", "append"):
        with open(p, "a") as f:
            f.write(content)
    else:
        p.write_text(content)
    return {"path": str(p), "bytes_written": len(content), "mode": mode}


def run_shell(command: str, timeout: int = 30) -> Dict:
    """执行 shell 命令"""
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, executable="/bin/bash"
        )
        out = r.stdout[:8000]
        err = r.stderr[:2000]
        return {
            "exit_code": r.returncode,
            "stdout": out,
            "stderr": err,
            "truncated": len(r.stdout) > 8000 or len(r.stderr) > 2000,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}


def list_dir(path: str = ".") -> Dict:
    """列目录"""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"not found: {p}"}
    if not p.is_dir():
        return {"error": f"not a dir: {p}"}
    entries = []
    for entry in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        try:
            entries.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            })
        except Exception:
            pass
    return {"path": str(p), "entries": entries[:100]}


def web_fetch(url: str, method: str = "GET", max_chars: int = 5000) -> Dict:
    """HTTP GET/POST,JSON 自动解析

    SSL: 优先用 certifi CA bundle(macOS python.org install 缺系统证书常见坑)
    失败时回退到 unverified(只用于调试,不应成默认)
    """
    import ssl
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "LocalAgent/0.1")
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ctype = resp.headers.get("Content-Type", "")
        parsed = None
        if "json" in ctype:
            try:
                parsed = json.loads(body)
            except Exception:
                pass
        truncated = False
        if len(body) > max_chars:
            body = body[:max_chars]
            truncated = True
        return {"status": 200, "content_type": ctype, "body": body,
                "parsed_json": parsed, "truncated": truncated}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}. "
                          f"提示: macOS Python 需要 certifi (pip3 install --user certifi)",
                "url": url, "method": method}


def rag_query(query: str, top_k: int = 5, category: str = None) -> Dict:
    """查 local-rag 服务(假设已启动)"""
    import urllib.request
    payload = {"query": query, "top_k": top_k, "use_bm25": True, "use_vector": True, "use_keyword": True}
    if category:
        payload["category"] = category
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(f"{RAG_BASE_URL}/api/query", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"rag service unreachable: {e}. 启动方式: cd ~/local-rag && uvicorn app.main:app --port 8000"}


# ============================================================
# 注册中心:工具名 -> (function, JSON schema)
# ============================================================

SKILL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "read_file": {
        "fn": read_file,
        "schema": {
            "name": "read_file",
            "description": "读取本地文件内容(支持文本文件,带行号截断)。用于查看代码、配置、文档。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件绝对路径,如 /Users/lix/file.py"},
                    "max_chars": {"type": "integer", "description": "最大字符数,默认 5000"},
                },
                "required": ["path"],
            },
        },
    },
    "write_file": {
        "fn": write_file,
        "schema": {
            "name": "write_file",
            "description": "写入内容到本地文件(自动创建父目录)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目标文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"},
                    "mode": {"type": "string", "enum": ["w", "a", "append"], "description": "w 覆盖 / a 或 append 追加"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "run_shell": {
        "fn": run_shell,
        "schema": {
            "name": "run_shell",
            "description": "执行 shell 命令(bash),返回 stdout/stderr/exit_code。适合 ls/cat/grep/git/curl 等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "完整 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时秒数,默认 30"},
                },
                "required": ["command"],
            },
        },
    },
    "list_dir": {
        "fn": list_dir,
        "schema": {
            "name": "list_dir",
            "description": "列出目录内容(前 100 项,目录优先)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径,默认当前目录"},
                },
            },
        },
    },
    "web_fetch": {
        "fn": web_fetch,
        "schema": {
            "name": "web_fetch",
            "description": "HTTP GET 请求,可获取网页/JSON API。返回 status/body/parsed_json。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "完整 URL"},
                    "max_chars": {"type": "integer", "description": "响应最大字符数"},
                },
                "required": ["url"],
            },
        },
    },
    "rag_query": {
        "fn": rag_query,
        "schema": {
            "name": "rag_query",
            "description": "在本地 RAG 知识库中检索相关文档(BM25+向量+关键词混合)。前提:RAG 服务在 localhost:8000 跑着。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询文本"},
                    "top_k": {"type": "integer", "description": "返回条数,默认 5"},
                    "category": {"type": "string", "description": "按业务分类过滤,可选"},
                },
                "required": ["query"],
            },
        },
    },
}


def get_tool_schemas() -> List[Dict]:
    """返回 OpenAI tools 格式的 schema 列表"""
    return [v["schema"] for v in SKILL_REGISTRY.values()]


def get_skill_names() -> List[str]:
    return list(SKILL_REGISTRY.keys())


def execute_skill(name: str, args: Dict) -> Dict:
    """执行一个技能,返回结果字典 (含 metrics 记录 + LangSmith tool trace)"""
    import time as _t
    from app.core.metrics import metrics

    # 未知 skill 直接返回
    if name not in SKILL_REGISTRY:
        metrics.record_tool(name, latency=0.0, ok=False, error="unknown skill")
        return {"error": f"unknown skill: {name}. available: {get_skill_names()}"}

    # LangSmith tool trace 包裹
    from app.core.observability import obs as _obs
    _ts = None
    if _obs.langsmith_enabled:
        try:
            from langsmith import trace as _lst
            _ts = _lst(
                name=f"tool:{name}",
                run_type="tool",
                inputs={"tool": name, "arguments": args},
            )
            _ts.__enter__()
        except Exception:
            _ts = None

    fn = SKILL_REGISTRY[name]["fn"]
    t0 = _t.time()
    ok = True
    err = ""
    try:
        result = fn(**args)
        if isinstance(result, dict) and result.get("error"):
            ok = False
            err = str(result.get("error"))[:200]
        return result
    except TypeError as e:
        ok = False
        err = f"invalid args: {e}"
        return {"error": f"invalid arguments for {name}: {e}"}
    except Exception as e:
        ok = False
        err = f"{type(e).__name__}: {e}"
        return {"error": f"execution failed: {type(e).__name__}: {e}"}
    finally:
        latency = _t.time() - t0
        metrics.record_tool(name, latency=latency, ok=ok, error=err)
        try:
            _obs.record_tool(name=name, latency=latency, ok=ok, args=args, error=err)
        except Exception:
            pass
        # 关闭 tool trace
        if _ts:
            try:
                if not ok and err:
                    # 失败也上报
                    _ts.__exit__(None, None, None)
                else:
                    _ts.__exit__(None, None, None)
            except Exception:
                pass