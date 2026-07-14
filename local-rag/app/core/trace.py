"""
结构化 trace 日志:
- 每个请求一个 trace_id(uuid 前 8 位)
- 用标准 logging 写 stdout,每行带 [trace=xxx] [stage=yyy] 便于 grep
- 提供 stage() 上下文管理器自动计时
"""
import logging
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Optional

from app.core.config import DATA_DIR

# 写文件 + stdout 双输出
LOG_FILE = DATA_DIR / "rag_trace.log"


class TraceLogger:
    def __init__(self):
        self.logger = logging.getLogger("rag.trace")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        fmt = logging.Formatter(
            "%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        # stdout
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        self.logger.addHandler(sh)
        # 文件
        try:
            fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
            fh.setFormatter(fmt)
            self.logger.addHandler(fh)
        except Exception:
            pass
        self.logger.propagate = False

    def emit(self, trace_id: str, stage: str, msg: str, **fields):
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"[trace={trace_id}] [stage={stage}] {msg}"
        if extra:
            line += " | " + extra
        self.logger.info(line)


_log = TraceLogger()


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def stage(trace_id: str, name: str, **fields):
    """stage 计时上下文:进入打 start,退出打 done"""
    t0 = time.time()
    _log.emit(trace_id, name, "start", **fields)
    try:
        yield
    except Exception as e:
        _log.emit(trace_id, name, "error",
                  err=f"{type(e).__name__}: {str(e)[:200]}",
                  ms=int((time.time() - t0) * 1000))
        raise
    _log.emit(trace_id, name, "done", ms=int((time.time() - t0) * 1000))


def log(trace_id: str, stage: str, msg: str, **fields):
    _log.emit(trace_id, stage, msg, **fields)
