"""简洁的控制台日志:每个阶段一行,方便 trace agent 跑哪步了

设计:
- 每条日志一个独立行,带 [TAG] 前缀 + 时间戳 + 阶段名
- TAG 颜色化 (sub-task / tool call / verify / final 用不同颜色)
- 默认输出到 stdout,可通过 set_log_file() 写到文件
- 不打印 token / 完整 LLM content (避免日志爆)

用法:
  from app.core.logger import log
  log.version("v5")
  log.query("帮我看 ~/local-rag")
  log.step("plan", "拆 3 个 sub-task: t1/t2/t3")
  log.tool("run_shell", "echo hi")
  log.verify("pass=True, t1 完成")
  log.final("代码片段: ...")
"""
import sys
import time
from datetime import datetime
from typing import Optional

# ANSI 颜色
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"
_GRAY = "\033[90m"

# tag -> color
_TAG_COLORS = {
    "VERSION": _BOLD + _CYAN,
    "QUERY": _BOLD + _YELLOW,
    "STEP": _BOLD + _BLUE,
    "PLAN": _MAGENTA,
    "EXEC": _BLUE,
    "TOOL": _CYAN,
    "VERIFY": _YELLOW,
    "FINAL": _BOLD + _GREEN,
    "ERROR": _BOLD + _RED,
    "INFO": _GRAY,
}

_log_file: Optional[str] = None


def set_log_file(path: Optional[str]):
    """设置日志文件路径,None 表示只输出 stdout"""
    global _log_file
    _log_file = path


def _emit(tag: str, msg: str, color: str = ""):
    """打印一条日志

    格式: [14:23:55] [TAG] message
    """
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{tag}] {msg}"
    if color:
        line = f"{color}{line}{_RESET}"
    print(line, file=sys.stdout, flush=True)
    if _log_file:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def version(name: str):
    """Agent 框架版本,每次 run 开头"""
    _emit("VERSION", f"framework = {name}", _TAG_COLORS["VERSION"])


def query(text: str):
    """原始 query"""
    short = text if len(text) < 100 else text[:97] + "..."
    _emit("QUERY", f"input = {short!r}", _TAG_COLORS["QUERY"])


def step(name: str, detail: str = ""):
    """某个阶段名,比如 'plan' / 'execute' / 'verify' / 'synth'"""
    msg = name + (f" — {detail}" if detail else "")
    _emit("STEP", msg, _TAG_COLORS["STEP"])


def plan(reasoning: str, subtask_names: list):
    """plan 阶段: 拆解结果"""
    sub_str = " / ".join(subtask_names)
    _emit("PLAN", f"{reasoning} → [{sub_str}]", _TAG_COLORS["PLAN"])


def exec_start(idx: int, total: int, name: str):
    """开始执行一个 sub-task"""
    _emit("EXEC", f"[{idx}/{total}] {name}", _TAG_COLORS["EXEC"])


def exec_done(idx: int, total: int, name: str, ok: bool, preview: str = ""):
    """完成一个 sub-task"""
    mark = "OK" if ok else "FAIL"
    msg = f"[{idx}/{total}] {name} → {mark}"
    if preview:
        # 截掉换行 + 限制长度
        clean = preview.replace("\n", " ").replace("\r", " ")
        if len(clean) > 80:
            clean = clean[:77] + "..."
        msg += f" | {clean}"
    color = _GREEN if ok else _RED
    _emit("EXEC", msg, color)


def tool(name: str, args_summary: str = ""):
    """调工具"""
    msg = name + (f"({args_summary})" if args_summary else "")
    _emit("TOOL", msg, _TAG_COLORS["TOOL"])


def tool_done(name: str, preview: str = ""):
    """工具返回"""
    if preview:
        clean = preview.replace("\n", " ").replace("\r", " ")
        if len(clean) > 100:
            clean = clean[:97] + "..."
        _emit("TOOL", f"{name} → {clean}", _TAG_COLORS["TOOL"])
    else:
        _emit("TOOL", f"{name} → (no output)", _TAG_COLORS["TOOL"])


def verify(passed: bool, completed: list, failed: list, notes: str = ""):
    """verifier 结论"""
    mark = "PASS" if passed else "FAIL"
    msg = f"{mark} | completed={completed} failed={failed}"
    if notes:
        clean = notes.replace("\n", " ")
        if len(clean) > 80:
            clean = clean[:77] + "..."
        msg += f" | {clean}"
    color = _GREEN if passed else _YELLOW
    _emit("VERIFY", msg, color)


def retry(task_id: str, reason: str, new_intent: str):
    """verifier 决定重做"""
    clean = reason.replace("\n", " ")
    if len(clean) > 60:
        clean = clean[:57] + "..."
    _emit("VERIFY", f"RETRY [{task_id}] {clean} → {new_intent[:60]}", _YELLOW)


def final(answer: str):
    """最终答案预览"""
    clean = answer.replace("\n", " ").replace("\r", " ")
    if len(clean) > 200:
        clean = clean[:197] + "..."
    _emit("FINAL", clean, _TAG_COLORS["FINAL"])


def error(msg: str):
    """错误"""
    _emit("ERROR", msg, _TAG_COLORS["ERROR"])


def info(msg: str):
    """其它信息"""
    _emit("INFO", msg, _TAG_COLORS["INFO"])
