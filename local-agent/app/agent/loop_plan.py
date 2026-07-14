"""v5: Plan → Execute → Verify → Synthesize 模式

把复杂任务显式拆解:
  1. PLANNER   —— LLM 把问题拆成 2-5 个 sub-tasks
  2. EXECUTOR  —— 对每个 sub-task 复用 v1 ReAct 跑(嵌套 trace)
  3. VERIFIER  —— 检查所有 sub-task 是否回答原问题,失败的重做(有 retry budget)
  4. SYNTHESIZER —— 把所有 sub-task 结果组合成自然语言答案

跟 v1/v2/v4 区别:
  - 用户能看到清晰的 sub-task 列表 + 各自是否完成
  - 失败/迷失有"补救机制"而不是简单 max_iter 切断
  - 多步任务的进度可观察

复杂度:
  - LLM 调用次数: 1 (plan) + N×M (N sub-tasks × 平均 M 轮) + 1 (verify) + 0-1 (retry) + 1 (synth)
  - 默认 max_subtasks=5, max_retries=2, 单 sub-task 用 v1 的 MAX_ITERATIONS (8)

可观测:
  - 每个 sub-task 独立 trace, 存在 run.subtask_runs[i].steps
  - verifier verdict 记录哪些 sub-task 通过 / 失败 / 重做
"""
import json
import time
import uuid
import re
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from app.llm.client import chat
from app.skills.registry import get_tool_schemas, execute_skill
from app.core.config import MAX_ITERATIONS
from app.core import logger as log
from app.core.metrics import metrics
from app.agent.loop import AgentStep, _extract_pseudo_tool_calls, _format_observation


# ============================================================
# Data structures
# ============================================================

@dataclass
class SubTask:
    """一个 sub-task 的描述"""
    id: str                  # uuid
    name: str                # "读 README 第一段"
    intent: str              # "需要从 ~/local-rag/README.md 读取项目介绍,提取主要功能"
    completed: bool = False
    attempt: int = 0         # 试了几次
    result: str = ""         # 子任务最终输出
    error: str = ""          # 最近一次错误


@dataclass
class AgentPlanRun:
    """v5 顶层 run 结果"""
    question: str
    subtasks: List[SubTask] = field(default_factory=list)
    final_answer: str = ""
    plan_reasoning: str = ""         # planner 的"为什么这么分"
    verdict: Dict = field(default_factory=dict)  # verifier 输出
    duration_s: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    total_tokens: int = 0
    iterations: int = 0              # 总 sub-task 轮数累计


# ============================================================
# Prompts
# ============================================================

PLAN_PROMPT = """你是 Planner。把用户问题拆成可执行的 sub-tasks。

要求:
1. 2-5 个 sub-task,不能超过 5 个
2. 每个 sub-task 必须能由"现有工具"完成(工具列表见下方)
3. sub-task 之间有逻辑顺序依赖的,在 dependencies 字段标 (e.g. ["t1"])
4. 简单问题("hello" / "echo hi")返回 1 个 sub-task: name="直接回答", intent=原问题
5. **必须返回严格 JSON**,格式:
{{
  "reasoning": "为什么这么拆",
  "subtasks": [
    {{"id": "t1", "name": "短标题", "intent": "具体意图 + 预期输出", "dependencies": []}},
    ...
  ]
}}

工具列表(供你参考):
{tools}

用户问题: {question}

只回 JSON,不要解释。"""


VERIFY_PROMPT = """你是 Verifier。检查 sub-tasks 的结果是否完整回答了用户原始问题。

输入:
- 原问题: {question}
- sub-tasks + results:

{subtasks_summary}

每个 sub-task 的 intent 都要求**具体的、可验证的事实/数据**(文件路径、数字、命令输出、API 端点等),不允许是寒暄/问候/承诺。

输出严格 JSON:
{{
  "pass": true/false,           // 整体是否通过
  "completed": ["t1", "t2"],   // 通过的 sub-task id
  "failed": [                   // 未通过的,需要重做
    {{
      "id": "t3",
      "reason": "为什么失败 / 缺什么信息 / result 是否只是寒暄",
      "retry_intent": "重做这个 sub-task 时应该怎么办(更具体,指明要调哪个工具)"
    }}
  ],
  "notes": "整体观察"
}}

判定标准:
- "回答了原问题" = 每个 sub-task 的 intent 都达到了 + 它们组合起来覆盖了原问题全部要点
- "未完成" 信号:
  • result 为空 / 含 error / 抛异常
  • result 看起来是寒暄/问候/承诺(如 "嗨"、"有什么可以帮你的"、"好的我来")而非具体事实
  • intent 要求具体数据但 result 没给出数字/路径/输出
  • 工具返回了真实数据但 result 没引用

只回 JSON,不要解释。"""


SYNTHESIZE_PROMPT = """你是 Synthesizer。基于已完成的 sub-tasks 给出最终自然语言答案给用户。

原问题: {question}

Sub-task 结果:
{subtasks_summary}

要求:
- 直接回答用户,不要罗列子任务过程(除非用户问"怎么做的")
- 如果有数据/路径/文件位置,在答案里明确给出
- 用中文
- 不要二次总结子任务,聚焦用户的原始问题
- **不暴露内部实现细节**: 不要在答案里出现 localhost 端口、内部 API 路径、stack trace、debug 信息等
- **数据真实性**: 不要编造事件/时间/人物。如果 sub-task 结果里包含明显过时或无关内容(如 7 月份提到"五一假期"),只引用 sub-task 实际返回的可靠数据,不确定就明确说"信息有限"
- 如果某个 sub-task 部分成功/部分失败,在答案中礼貌说明哪部分信息缺失,但不要提及失败原因的技术细节

如果子任务本身没完成,在答案开头说明哪部分信息缺失。"""


# ============================================================
# Helpers
# ============================================================

def _format_tools_for_plan() -> str:
    """给 Planner 看的工具列表(简化版)"""
    tools = get_tool_schemas()
    out = []
    for t in tools:
        f = t.get("function", t)
        name = f.get("name", "?")
        desc = f.get("description", "")[:80]
        params = list(f.get("parameters", {}).get("properties", {}).keys())
        out.append(f"- {name}({', '.join(params)}): {desc}")
    return "\n".join(out)


def _format_subtasks_summary(subtasks: List[SubTask]) -> str:
    """把 subtasks 渲染成 verifier/synth 用得简洁列表"""
    out = []
    for i, st in enumerate(subtasks, 1):
        status = "✓" if st.completed else ("✗" if st.attempt > 0 else "○")
        result_preview = (st.result or st.error)[:300]
        out.append(f"[{status}] #{i} {st.id} {st.name}\n"
                   f"    intent: {st.intent}\n"
                   f"    attempt: {st.attempt}\n"
                   f"    result: {result_preview}\n")
    return "\n".join(out)


# ============================================================
# Phase 1: Planner
# ============================================================

def _is_simple_task(question: str) -> bool:
    """判断是不是"单步就能搞定"的任务 —— 用 v1 fast path

    信号:
    - 短问题 (< 30 字符)
    - 没"如何/帮我/总结" 等多步关键词
    - 没多问号 / 没列表
    - 不需要查资料/多文件分析/写代码
    """
    q = question.strip()
    # 明显复杂信号
    complex_keywords = [
        "怎么", "如何", "为什么", "帮我", "请",
        "总结", "分析", "解释", "讲解", "对比",
        "梳理", "比较",
        "多个", "几个", "所有", "全部",
        "并且", "同时", "然后",
        "修复", "实现", "开发", "写一个",
        "从... 到...", "如下", "例如",
    ]
    long_signals = q.count("?") >= 2 or q.count("?") >= 2 or q.count("?") >= 2
    multiline = q.count("\n") >= 2
    has_numbered = bool(re.search(r"\d+[.\u3001)]", q))  # 1. 2. 3. 或 1、 2) 3)
    has_keywords = any(kw in q for kw in complex_keywords)
    too_long = len(q) > 60

    if has_keywords or has_numbered or multiline or long_signals or too_long:
        return False

    # 简单信号:命令/单查询/问候
    simple_keywords = [
        "echo", "ls", "cat", "pwd", "whoami", "date",
        "现在几点", "今天几号", "星期几", "时间",
        "什么是", "定义",
        "你好", "hi", "hello", "嗨",
        "目录", "文件",
        "列出", "看一下", "给我", "查看",
    ]
    has_simple = any(kw in q.lower() for kw in simple_keywords)

    # fallback:短 + 无复杂信号 = 简单
    return len(q) < 30 or has_simple


def _is_greeting(q: str) -> bool:
    """纯寒暄/问候 → 不进 v5 plan, 直接让 v1 LLM final"""
    q = q.strip().lower().rstrip(".!?~～。,，").strip()
    if not q:
        return True
    greetings = {
        "hi", "hii", "hey", "yo", "hello", "你好", "嗨", "哈喽", "嘿", "喂",
        "早上好", "中午好", "下午好", "晚上好", "早",
        "good morning", "good afternoon", "good evening",
    }
    if q in greetings:
        return True
    greeting_chars = "你好嗨哈喽喂嘿呀啊"
    short = q.replace(" ", "")
    if len(short) <= 4 and all(c in greeting_chars + "!~～,.。" for c in short):
        return True
    return False


def _plan(question: str) -> tuple[str, List[SubTask]]:
    """LLM 一次调用,返回 (reasoning, subtasks)

    优化: 简单任务(_is_simple_task)跳过 LLM planner,直接给 1 个 sub-task
    """
    log.step("plan", "判断任务复杂度")

    # Fast path: 简单任务直接跳过 planner
    if _is_simple_task(question):
        log.plan("[fast-path] 简单任务", [f"t1: {question[:30]}"])
        return (
            f"[fast-path] 问题很短且无复杂关键词,直接当作单 sub-task 处理: {question}",
            [SubTask(id="t1", name="直接回答", intent=question)]
        )

    log.info("复杂任务,调用 LLM planner...")
    tools = _format_tools_for_plan()
    prompt = PLAN_PROMPT.format(tools=tools, question=question)

    resp = chat(
        [{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    content = resp.get("content", "")

    # 尝试解析 JSON object (不是 array)
    import re
    obj_text = content.strip()
    # 抓 { 到对应 }
    # 由于 minimax 的输出可能混入 reasoning 或 markdown,做 robust parse
    parsed = _extract_json_object(content)

    if not parsed or "subtasks" not in parsed:
        log.error("planner 未返回合法 JSON,降级为单 sub-task")
        # fallback: 单个 sub-task
        return ("[planner 未返回合法 JSON,降级为单 sub-task]", [
            SubTask(id="t1", name="直接回答", intent=question)
        ])

    reasoning = parsed.get("reasoning", "")
    subtasks = []
    for raw in parsed["subtasks"][:5]:  # 硬上限 5
        st = SubTask(
            id=raw.get("id", f"t{len(subtasks)+1}"),
            name=raw.get("name", f"sub-task {len(subtasks)+1}"),
            intent=raw.get("intent", question),
        )
        subtasks.append(st)
    if not subtasks:
        subtasks = [SubTask(id="t1", name="直接回答", intent=question)]
    log.plan(reasoning, [f"{s.id}: {s.name}" for s in subtasks])
    return reasoning, subtasks

# ============================================================
# Phase 2: Executor (复用 v1 ReAct)
# ============================================================

def _execute_subtask(
    subtask: SubTask,
    question: str,
    history: List[Dict],
    max_iters: int = MAX_ITERATIONS,
) -> List[AgentStep]:
    """对单个 sub-task 跑一次 ReAct, 返回 step trace

    副作用: 更新 subtask.result / .completed / .attempt,并写入 metrics
    """
    sub_start = time.time()
    steps: List[AgentStep] = []
    msgs = [
        {"role": "system",
         "content": (
             "你是一个 Agentic 助手,专注完成这一个 sub-task:\n"
             f"NAME: {subtask.name}\n"
             f"INTENT: {subtask.intent}\n"
             f"ORIGINAL QUESTION (参考): {question[:200]}\n\n"
             + "⚠️ 严格要求:\n"
             + "1. 如果 sub-task 需要外部信息,必须通过 tool_calls 字段调用工具\n"
             + "2. 不许只在文字里写'我帮你查了'——必须真的发起 tool_call\n"
             + "3. 拿到工具返回结果后,再总结这个 sub-task 的具体输出\n"
             + "4. 简单寒暄('hi'/'hello')会直接判失败\n"
         )},
        {"role": "user",
         "content": f"请完成这个 sub-task: {subtask.name}\n\n具体意图: {subtask.intent}\n\n【提醒】如果需要查信息必须真的调工具,别只用文字回答。"},
    ]
    if history:
        msgs.extend(history[-4:])  # 只保留最近 4 轮 history

    tool_schemas = get_tool_schemas()

    for it in range(1, max_iters + 1):
        try:
            resp = chat(msgs, tools=tool_schemas, temperature=0.3)
        except Exception as e:
            steps.append(AgentStep(
                iteration=it, thought=f"[LLM ERROR: {e}]",
                action="error", action_input={}, observation=str(e)[:200],
            ))
            break

        content = resp.get("content", "") or ""
        pseudo = _extract_pseudo_tool_calls(content, tool_schemas)
        calls = (resp.get("tool_calls") or []) + pseudo

        # assistant message
        am = {"role": "assistant", "content": content}
        if calls:
            am["tool_calls"] = [
                {"id": tc.get("id", f"pseudo_{it}_{i}"), "type": "function",
                 "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                for i, tc in enumerate(calls)
            ]
        msgs.append(am)

        if not calls:
            steps.append(AgentStep(
                iteration=it, thought=content,
                action="final", action_input={},
                observation=content[:500],
            ))
            subtask.result = content
            subtask.completed = True
            subtask.attempt += 1
            break  # 不再 return, finally 统一记录

        for tc in calls:
            # 简化 args 显示: 截断
            args_str = json.dumps(tc["arguments"], ensure_ascii=False)
            if len(args_str) > 80:
                args_str = args_str[:77] + "..."
            log.tool(tc["name"], args_str)
            obs = execute_skill(tc["name"], tc["arguments"])
            obs_text = _format_observation(obs)
            steps.append(AgentStep(
                iteration=it, thought=content,
                action=tc["name"], action_input=tc["arguments"],
                observation=obs_text[:500],
            ))
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"pseudo_{it}_0"),
                "content": obs_text,
            })
            log.tool_done(tc["name"], obs_text)

    # 走到这里 = max_iters 用完还没 final (或上面 break 出来)
    if not subtask.completed:
        fallback = steps[-1].observation if steps else "(no steps)"
        subtask.result = fallback
        subtask.attempt += 1

    # 记录 metric
    sub_duration = time.time() - sub_start
    metrics.record_subtask(
        sub_id=subtask.id,
        name=subtask.name,
        ok=subtask.completed,
        attempt=subtask.attempt,
        duration=sub_duration,
    )
    return steps


# ============================================================
# Phase 3: Verifier
# ============================================================

def _verify(question: str, subtasks: List[SubTask]) -> Dict:
    """LLM 检查所有 sub-task 是否回答原问题, 决定重做哪些"""
    summary = _format_subtasks_summary(subtasks)
    prompt = VERIFY_PROMPT.format(question=question, subtasks_summary=summary)
    try:
        resp = chat([{"role": "user", "content": prompt}], temperature=0.1)
        content = resp.get("content", "") or ""
        parsed = _extract_json_object(content)
        if parsed:
            return parsed
    except Exception as e:
        # parse 失败 -> 保守:不 pass,标记所有未完成的需重做
        failed = [{"id": st.id, "reason": f"[verifier error: {e}]",
                   "retry_intent": st.intent}
                  for st in subtasks if not st.completed]
        return {"pass": False, "completed": [s.id for s in subtasks if s.completed],
                "failed": failed, "notes": f"[verifier parse error: {e}]"}
    # 没匹配到 JSON 也保守
    failed = [{"id": st.id, "reason": "[verifier no json]",
               "retry_intent": st.intent}
              for st in subtasks if not st.completed]
    return {"pass": False, "completed": [s.id for s in subtasks if s.completed],
            "failed": failed, "notes": "[verifier no json]"}


def _extract_json_object(text: str) -> Optional[Dict]:
    """从 LLM 输出里抽一个 JSON object.

    容忍:
      - ```json ... ``` 代码块
      - 裸 { ... } (贪婪到最后一个 })
      - reasoning 文字混在前/后/中间
      - 单行紧凑 / 多行格式都 OK
    """
    import re
    # 1) ```json ... ``` 或 ``` ... ```
    for pat in [r"```(?:json)?\s*(\{[\s\S]*?\})\s*```",
                r"```(?:json)?\s*(\{[\s\S]*\})\s*```"]:
        m = re.search(pat, text)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    # 2) 找 { ... } (用括号配对,不是 regex)
    start = text.find("{")
    while start != -1:
        depth = 0
        end = start
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if depth == 0 and end > start:
            candidate = text[start:end+1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        start = text.find("{", start + 1)
    return None


# ============================================================
# Phase 4: Synthesizer
# ============================================================

def _synthesize(question: str, subtasks: List[SubTask]) -> str:
    """LLM 综合所有 sub-task 结果给最终答案"""
    summary = _format_subtasks_summary(subtasks)
    prompt = SYNTHESIZE_PROMPT.format(question=question, subtasks_summary=summary)
    try:
        resp = chat([{"role": "user", "content": prompt}], temperature=0.3)
        return resp.get("content", "") or "(synth 空)"
    except Exception as e:
        # fallback: 直接拼接
        parts = [f"[{st.name}] {st.result[:200]}" for st in subtasks]
        return f"[synth error: {e}]\n\n" + "\n\n".join(parts)


# ============================================================
# Main entry
# ============================================================

def run(
    question: str,
    history: List[Dict] = None,
    max_subtasks: int = 5,
    max_retries: int = 2,
) -> AgentPlanRun:
    """v5 Plan-Execute-Verify-Synthesize 主流程

    返回 AgentPlanRun:
      - subtasks: 拆解结果, 每个 SubTask 含 attempt/result/completed
      - verdict: verifier 输出
      - final_answer: 合成答案
      - duration_s, iterations, total_tokens

    LangSmith: 整个 run 包成 chain trace, 里面嵌套
      - plan (chain)
      - execute_subtask (chain per subtask)
      - verify (chain)
      - synthesize (chain)
    """
    from app.core.observability import obs as _obs
    _ts = None
    if _obs.langsmith_enabled:
        try:
            from langsmith import trace as _lst
            _ts = _lst(
                name="v5_agent_run",
                run_type="chain",
                inputs={"question": question, "framework": "v5-plan-execute-verify"},
            )
            _ts.__enter__()
        except Exception:
            _ts = None

    try:
        return _run_inner(question, history, max_subtasks, max_retries)
    finally:
        if _ts:
            try:
                _ts.__exit__(None, None, None)
            except Exception:
                pass


def _run_inner(
    question: str,
    history: List[Dict] = None,
    max_subtasks: int = 5,
    max_retries: int = 2,
) -> AgentPlanRun:
    """run() 的实际实现,被 LangSmith chain trace 包裹"""
    out = AgentPlanRun(question=question, started_at=time.time())
    log.version("v5-plan-execute-verify")
    log.query(question)
    run_id = metrics.start_run("v5-plan-execute-verify", question=question)
    log.step("plan", "判断任务复杂度")

    # Phase 1: Plan
    reasoning, subtasks = _plan(question)
    out.plan_reasoning = reasoning
    out.subtasks = subtasks

    # Phase 2: Execute (first pass)
    log.step("execute", f"开始跑 {len(subtasks)} 个 sub-task")
    for i, st in enumerate(subtasks, 1):
        log.exec_start(i, len(subtasks), f"{st.id}: {st.name}")
        _execute_subtask(st, question, history)
        log.exec_done(i, len(subtasks), f"{st.id}: {st.name}", st.completed, st.result or st.error)
        out.iterations += st.attempt or 1

    # Phase 3: Verify + Retry loop
    log.step("verify", "verifier 检查 sub-task 是否回答原问题")
    for retry_round in range(max_retries):
        verdict = _verify(question, subtasks)
        out.verdict = verdict
        completed = verdict.get("completed", [])
        failed_ids = [r.get("id") for r in verdict.get("failed", [])]
        log.verify(
            passed=verdict.get("pass") is True,
            completed=completed,
            failed=failed_ids,
            notes=verdict.get("notes", ""),
        )

        if verdict.get("pass") is True:
            break

        retries = verdict.get("failed", [])
        if not retries:
            break

        log.step(f"retry-{retry_round+1}", f"verifier 决定重做 {len(retries)} 个")
        for r in retries:
            idx = next((i for i, st in enumerate(subtasks) if st.id == r.get("id")), None)
            if idx is None:
                continue
            # 用 retry_intent 更明确的指令重做
            subtasks[idx].intent = r.get("retry_intent") or subtasks[idx].intent
            subtasks[idx].completed = False
            subtasks[idx].error = r.get("reason", "")
            log.retry(subtasks[idx].id, r.get("reason", ""), subtasks[idx].intent)
            _execute_subtask(subtasks[idx], question, history)
            log.exec_done(idx+1, len(subtasks),
                          f"{subtasks[idx].id}: {subtasks[idx].name}",
                          subtasks[idx].completed,
                          subtasks[idx].result or subtasks[idx].error)
            out.iterations += 1

    # Phase 4: Synthesize
    log.step("synthesize", "综合所有 sub-task 结果")
    out.final_answer = _synthesize(question, subtasks)
    log.final(out.final_answer)

    out.finished_at = time.time()
    out.duration_s = out.finished_at - out.started_at
    log.info(f"done — duration={out.duration_s:.1f}s iterations={out.iterations}")
    metrics.end_run(
        run_id=run_id,
        ok=bool(out.final_answer and "[synth error" not in out.final_answer),
        final_answer=out.final_answer,
        iterations=out.iterations,
        tokens=out.total_tokens,
    )
    return out


def to_dict(run: AgentPlanRun) -> Dict:
    """序列化给前端"""
    return {
        "question": run.question,
        "plan_reasoning": run.plan_reasoning,
        "subtasks": [
            {
                "id": st.id,
                "name": st.name,
                "intent": st.intent,
                "completed": st.completed,
                "attempt": st.attempt,
                "result_preview": (st.result or st.error)[:500],
            }
            for st in run.subtasks
        ],
        "verdict": run.verdict,
        "final_answer": run.final_answer,
        "iterations": run.iterations,
        "duration_s": round(run.duration_s, 2),
    }
