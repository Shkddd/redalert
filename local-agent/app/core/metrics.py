"""Agent 监控指标收集:内存版,带磁盘持久化 (JSONL)

指标分类:
- run_*: 每次完整 agent run 的汇总 (framework / ok / duration / tokens / iterations)
- llm_*: 每次 LLM 调用的细节 (model / latency / tokens / ok / error)
- tool_*: 每次工具调用的细节 (name / latency / ok / error)
- subtask_*: v5 sub-task 完成 (id / attempt / ok / duration)

用法:
    from app.core.metrics import metrics
    metrics.start_run("v5", question="echo hi")
    metrics.record_llm(latency=1.2, model="MiniMax-M3", ok=True, tokens=150)
    metrics.record_tool("run_shell", latency=0.05, ok=True)
    metrics.end_run(ok=True, final_answer="hi")

存储:
- 内存: Counter / Histogram (按时间窗口,默认保留最近 1000 条)
- 磁盘: ~/local-agent/logs/metrics.jsonl (append-only, 每条一行 JSON)
"""
import json
import time
import threading
import statistics
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Deque


class _Histogram:
    """轻量 histogram: 记录最近 N 个值 + 计算 avg/p50/p95/max"""

    def __init__(self, max_size: int = 200):
        self.values: Deque[float] = deque(maxlen=max_size)

    def add(self, v: float):
        self.values.append(v)

    def stats(self) -> Dict:
        if not self.values:
            return {"count": 0, "avg": 0, "p50": 0, "p95": 0, "max": 0}
        vs = sorted(self.values)
        n = len(vs)
        return {
            "count": n,
            "avg": round(sum(vs) / n, 3),
            "p50": round(vs[n // 2], 3),
            "p95": round(vs[int(n * 0.95)], 3) if n >= 20 else round(vs[-1], 3),
            "max": round(max(vs), 3),
        }


class _Counter:
    """简单计数器: total / success / fail"""

    def __init__(self):
        self.total = 0
        self.success = 0
        self.fail = 0

    def add(self, ok: bool):
        self.total += 1
        if ok:
            self.success += 1
        else:
            self.fail += 1

    def stats(self) -> Dict:
        return {
            "total": self.total,
            "success": self.success,
            "fail": self.fail,
            "success_rate": round(self.success / self.total, 3) if self.total else 0,
        }


class MetricsStore:
    """全部 metrics 的中心存储"""

    def __init__(self, log_dir: Optional[str] = None, max_recent: int = 500):
        self._lock = threading.Lock()
        self.max_recent = max_recent

        # 按 framework 分组 run 计数
        self.runs_by_fw: Dict[str, _Counter] = defaultdict(_Counter)
        self.run_latency_by_fw: Dict[str, _Histogram] = defaultdict(lambda: _Histogram(max_size=200))
        self.run_iterations_by_fw: Dict[str, _Histogram] = defaultdict(lambda: _Histogram(max_size=200))
        self.total_tokens = 0

        # LLM
        self.llm_counter = _Counter()
        self.llm_latency = _Histogram(max_size=300)
        self.llm_tokens = _Histogram(max_size=300)

        # Tool
        self.tool_counter = _Counter()
        self.tool_by_name: Dict[str, _Counter] = defaultdict(_Counter)
        self.tool_latency: _Histogram = _Histogram(max_size=300)
        self.tool_latency_by_name: Dict[str, _Histogram] = defaultdict(lambda: _Histogram(max_size=200))

        # v5 sub-task
        self.subtask_counter = _Counter()
        self.subtask_retries = 0  # 累计 retry 次数

        # 最近的 raw events (前端显示)
        self.recent_runs: Deque[Dict] = deque(maxlen=max_recent)
        self.recent_llm: Deque[Dict] = deque(maxlen=max_recent)
        self.recent_tools: Deque[Dict] = deque(maxlen=max_recent)

        # 当前活跃 run (用于实时跟踪)
        self.active_runs: Dict[str, Dict] = {}

        # 磁盘日志
        if log_dir:
            self.log_dir = Path(log_dir)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = self.log_dir / "metrics.jsonl"
        else:
            # 默认 ~/local-agent/logs/metrics.jsonl
            self.log_dir = Path.home() / "local-agent" / "logs"
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = self.log_dir / "metrics.jsonl"

    # ============================================================
    # Run tracking
    # ============================================================

    def start_run(self, framework: str, question: str, session_id: str = "default") -> str:
        run_id = f"run_{int(time.time() * 1000)}_{threading.get_ident()}"
        with self._lock:
            self.active_runs[run_id] = {
                "id": run_id,
                "framework": framework,
                "question": question[:200],
                "session_id": session_id,
                "started_at": time.time(),
                "started_at_iso": datetime.now().isoformat(timespec="seconds"),
                "ok": None,
                "iterations": 0,
                "total_tokens": 0,
            }
        return run_id

    def end_run(self, run_id: str, ok: bool, final_answer: str = "",
                iterations: int = 0, tokens: int = 0):
        with self._lock:
            if run_id not in self.active_runs:
                return
            r = self.active_runs.pop(run_id)
            duration = time.time() - r["started_at"]
            framework = r["framework"]

            self.runs_by_fw[framework].add(ok)
            self.run_latency_by_fw[framework].add(duration)
            self.run_iterations_by_fw[framework].add(iterations)
            self.total_tokens += tokens

            event = {
                "type": "run",
                "ts": r["started_at_iso"],
                "run_id": run_id,
                "framework": framework,
                "session_id": r["session_id"],
                "question": r["question"],
                "ok": ok,
                "duration_s": round(duration, 3),
                "iterations": iterations,
                "tokens": tokens,
                "final_preview": final_answer[:150].replace("\n", " "),
            }
            self.recent_runs.append(event)
            self._append_disk(event)

    # ============================================================
    # LLM tracking
    # ============================================================

    def record_llm(self, latency: float, model: str, ok: bool,
                   prompt_tokens: int = 0, completion_tokens: int = 0,
                   error: str = ""):
        with self._lock:
            self.llm_counter.add(ok)
            self.llm_latency.add(latency)
            total_tok = prompt_tokens + completion_tokens
            if total_tok:
                self.llm_tokens.add(total_tok)

            event = {
                "type": "llm",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "model": model,
                "latency_s": round(latency, 3),
                "ok": ok,
                "tokens": total_tok,
                "error": error[:200],
            }
            self.recent_llm.append(event)
            self._append_disk(event)

    # ============================================================
    # Tool tracking
    # ============================================================

    def record_tool(self, name: str, latency: float, ok: bool, error: str = ""):
        with self._lock:
            self.tool_counter.add(ok)
            self.tool_by_name[name].add(ok)
            self.tool_latency.add(latency)
            self.tool_latency_by_name[name].add(latency)

            event = {
                "type": "tool",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "name": name,
                "latency_s": round(latency, 3),
                "ok": ok,
                "error": error[:200],
            }
            self.recent_tools.append(event)
            self._append_disk(event)

    # ============================================================
    # Sub-task (v5)
    # ============================================================

    def record_subtask(self, sub_id: str, name: str, ok: bool, attempt: int,
                       duration: float):
        with self._lock:
            self.subtask_counter.add(ok)
            if attempt > 1:
                self.subtask_retries += 1
            event = {
                "type": "subtask",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "id": sub_id,
                "name": name,
                "ok": ok,
                "attempt": attempt,
                "duration_s": round(duration, 3),
            }
            self._append_disk(event)

    # ============================================================
    # Snapshot / serialize
    # ============================================================

    def snapshot(self) -> Dict:
        """给前端 /monitor 页面用的完整快照"""
        from app.core.observability import obs
        with self._lock:
            return {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "active_runs": list(self.active_runs.values()),
                "observability": {
                    "langsmith": obs.langsmith_enabled,
                    "agentops": obs.agentops_enabled,
                    "otel": obs.otel_enabled,
                    "langsmith_project": getattr(obs, "langsmith_project", None),
                },
                "totals": {
                    "runs": sum(c.total for c in self.runs_by_fw.values()),
                    "success_runs": sum(c.success for c in self.runs_by_fw.values()),
                    "fail_runs": sum(c.fail for c in self.runs_by_fw.values()),
                    "llm_calls": self.llm_counter.total,
                    "tool_calls": self.tool_counter.total,
                    "subtasks": self.subtask_counter.total,
                    "subtask_retries": self.subtask_retries,
                    "total_tokens": self.total_tokens,
                },
                "by_framework": {
                    fw: {
                        "runs": self.runs_by_fw[fw].stats(),
                        "latency": self.run_latency_by_fw[fw].stats(),
                        "iterations": self.run_iterations_by_fw[fw].stats(),
                    }
                    for fw in sorted(self.runs_by_fw.keys())
                },
                "llm": {
                    "calls": self.llm_counter.stats(),
                    "latency": self.llm_latency.stats(),
                    "tokens": self.llm_tokens.stats(),
                },
                "tools": {
                    "all": self.tool_counter.stats(),
                    "by_name": {
                        name: {
                            "calls": self.tool_by_name[name].stats(),
                            "latency": self.tool_latency_by_name[name].stats(),
                        }
                        for name in sorted(self.tool_by_name.keys())
                    },
                },
                "recent": {
                    "runs": list(self.recent_runs)[-20:],
                    "llm": list(self.recent_llm)[-20:],
                    "tools": list(self.recent_tools)[-20:],
                },
            }

    # ============================================================
    # Internal
    # ============================================================

    def _append_disk(self, event: Dict):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 不要让 logging 失败搞死主流程


# 单例
metrics = MetricsStore()
