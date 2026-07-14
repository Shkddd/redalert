"""Agent 核心循环:Plan → ReAct(分析-选技能-执行-验证) → 收尾

循环结构:
  Step 1: PLANNING —— LLM 拿到用户问题,先出 Plan(可选)
  Step 2: REACT 循环(最多 MAX_ITERATIONS 轮)
    a. THINK: LLM 看 history,决定下一步动作(调用技能 / 直接回答 / 完成)
    b. ACT: 执行技能
    c. OBSERVE: 把结果塞回 history
    d. VERIFY: 隐式通过 LLM 下一轮决策
  Step 3: FINAL —— LLM 基于所有 Observation 给最终答案
"""
import json
import time
from typing import List, Dict, Iterator
from dataclasses import dataclass, field

from app.llm.client import chat
from app.skills.registry import get_tool_schemas, execute_skill
from app.core.config import MAX_ITERATIONS
from app.core import logger as log
from app.core.metrics import metrics


SYSTEM_PROMPT = """你是一个 Agentic 助手,能通过循环调用工具来回答用户问题。

工作模式:
1. 分析(Analyze): 理解用户意图,拆解为子任务
2. 规划(Plan): 必要时先列出执行计划
3. 选技能(Select): 从可用工具中选择最合适的
4. 执行(Execute): 调用工具获取结果
5. 验证(Verify): 检查结果是否推进目标,若未推进则重新规划
6. 收尾(Finish): 收集足够信息后给出最终回答

规则:
- 一次只调用一个工具(除非明确知道多个独立信息)
- 调用工具后要基于结果决定下一步
- 看到结果已足够回答时,直接用自然语言给出 final answer,不再调工具
- 避免重复执行相同的工具调用
- 重要信息(文件路径、用户偏好)要记住
- 当前用户: macOS, home=/Users/lix,~ 展开到 /Users/lix
- 路径用绝对路径,别用 ~ 开头(自己拼完整路径)
- **【重要】如果需要调用工具,必须真的发起 tool_call,不要只在文字里写"我会调用 xxx"。** 模型只接受通过 tool_calls 字段发起的实际调用。
- **【重要】任务有多个子步骤时,完成一个再决定下一个;不要提前在文字里宣布后续步骤。**
- 当 tool 还没返回你需要的具体信息时(比如要读文件内容、要查 RAG),不要在没拿到结果前就 final。

可用工具会自动提供给你。当你觉得信息足够时,直接用文字回答用户即可。
"""


@dataclass
class AgentStep:
    """一次循环的记录"""
    iteration: int
    thought: str
    action: str  # 工具名 or "final"
    action_input: Dict
    observation: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentRun:
    """一次完整任务运行"""
    question: str
    plan: str = ""
    steps: List[AgentStep] = field(default_factory=list)
    final_answer: str = ""
    total_tokens: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0


def _format_observation(obs: Dict) -> str:
    """把工具结果压成短文本塞进 history"""
    if "error" in obs and len(obs) == 1:
        return f"Error: {obs['error']}"
    # 序列化
    try:
        s = json.dumps(obs, ensure_ascii=False, indent=2)
    except Exception:
        s = str(obs)
    if len(s) > 3000:
        s = s[:3000] + f"\n... [truncated, original {len(s)} chars]"
    return s


def _format_tools_for_prompt() -> str:
    """生成可读的工具描述,放在 system prompt 末尾(没用 tool_calls API 时备用)"""
    schemas = get_tool_schemas()
    lines = ["\n可用工具列表:"]
    for s in schemas:
        lines.append(f"\n## {s['name']}")
        lines.append(f"  用途: {s['description']}")
        params = s.get("parameters", {}).get("properties", {})
        if params:
            lines.append(f"  参数: {', '.join(params.keys())}")
    return "\n".join(lines)


def run(question: str, history: List[Dict] = None) -> AgentRun:
    """
    运行一次 agent 循环,返回完整 trace
    history: 多轮对话记忆(可选)

    LangSmith: 整个 run 包成 chain trace (run_type="chain"),
    里面嵌套 llm + tool traces
    """
    from app.core.observability import obs as _obs
    _ts = None
    if _obs.langsmith_enabled:
        try:
            from langsmith import trace as _lst
            _ts = _lst(
                name="agent_run",
                run_type="chain",
                inputs={"question": question, "framework": "v1-react"},
            )
            _ts.__enter__()
        except Exception:
            _ts = None

    try:
        return _run_inner(question, history)
    finally:
        if _ts:
            try:
                _ts.__exit__(None, None, None)
            except Exception:
                pass


def _run_inner(question: str, history: List[Dict] = None) -> AgentRun:
    """run() 的实际实现,被 LangSmith chain trace 包裹"""
    run = AgentRun(question=question)
    log.version("v1-react")
    log.query(question)
    log.step("react", f"开始最多 {MAX_ITERATIONS} 轮 ReAct 循环")
    m_run_id = metrics.start_run("v1-react", question=question)

    # 1. 准备 messages
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + _format_tools_for_prompt()},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    tool_schemas = get_tool_schemas()

    # 2. ReAct 循环
    for iteration in range(1, MAX_ITERATIONS + 1):
        log.step(f"iter-{iteration}", "LLM think + act")
        # THINK + ACT: 让 LLM 决定下一步
        try:
            resp = chat(messages, tools=tool_schemas, temperature=0.3)
        except Exception as e:
            run.final_answer = f"[LLM 调用失败: {e}]"
            log.error(f"LLM 失败: {e}")
            break

        run.total_tokens += resp.get("_usage", {}).get("completion_tokens", 0)

        # 把 LLM 响应加入 messages
        assistant_msg = {
            "role": "assistant",
            "content": resp.get("content", "") or "",
        }
        # 兼容:有些 LLM 在 content 文本里写伪 tool_call(如 "functions.read_file(...)")
        # 尝试从 content 里抽 JSON 风格调用
        pseudo_calls = _extract_pseudo_tool_calls(resp.get("content", ""), tool_schemas)
        real_calls = resp.get("tool_calls", [])
        all_calls = real_calls + pseudo_calls

        if all_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"] if "id" in tc else f"pseudo_{iteration}_{i}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                }
                for i, tc in enumerate(all_calls)
            ]
        messages.append(assistant_msg)

        # 解析 LLM 决策
        thought = resp.get("content", "")

        if not all_calls:
            # 没有工具调用 → 视为最终回答
            step = AgentStep(
                iteration=iteration,
                thought=thought,
                action="final",
                action_input={},
            )
            run.steps.append(step)
            run.final_answer = thought or "(空回答)"
            log.step(f"iter-{iteration}", "final — 无 tool_call, 给最终答案")
            break

        # 执行工具
        for tc in all_calls:
            name = tc["name"]
            args = tc["arguments"]
            step = AgentStep(
                iteration=iteration,
                thought=thought,
                action=name,
                action_input=args,
            )

            # 日志: tool call
            args_str = json.dumps(args, ensure_ascii=False)
            if len(args_str) > 80:
                args_str = args_str[:77] + "..."
            log.tool(name, args_str)

            obs = execute_skill(name, args)
            obs_text = _format_observation(obs)
            step.observation = obs_text[:500]
            run.steps.append(step)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"pseudo_{iteration}_0"),
                "content": obs_text,
            })

            log.tool_done(name, obs_text)

    else:
        run.final_answer = f"[已达 {MAX_ITERATIONS} 轮上限,自动收尾]"
        log.error(f"已达 {MAX_ITERATIONS} 轮上限,自动收尾")

    run.finished_at = time.time()
    # 记录 run metric
    iterations = len(run.steps)
    ok = bool(run.final_answer) and "[LLM" not in (run.final_answer or "") and "[已达" not in (run.final_answer or "")
    metrics.end_run(
        run_id=m_run_id,
        ok=ok,
        final_answer=run.final_answer or "",
        iterations=iterations,
        tokens=run.total_tokens,
    )
    return run


def _extract_pseudo_tool_calls(content: str, tool_schemas: List[Dict]) -> List[Dict]:
    """从 LLM 的 text 内容里识别"伪 tool_call"(如 functions.read_file({...}))
    一些 LLM 不善用 tool_calls 字段,会把它写在文字里。
    """
    import re
    if not content:
        return []
    tool_names = [t["name"] for t in tool_schemas]
    # 匹配 tool_name({...}) 或 tool_name(...)
    pattern = r'\b(' + '|'.join(tool_names) + r')\s*\(\s*(\{[^{}]*\{[^{}]*\}[^{}]*\}|\{[^}]*\}|[^)]*)\)'
    found = []
    seen = set()
    for m in re.finditer(pattern, content):
        name = m.group(1)
        raw = m.group(2).strip()
        if name in seen:
            continue
        seen.add(name)
        # 尝试解析 JSON
        args = {}
        if raw.startswith("{"):
            try:
                args = json.loads(raw)
            except Exception:
                # 试单引号
                try:
                    args = json.loads(raw.replace("'", '"'))
                except Exception:
                    args = {}
        found.append({"name": name, "arguments": args})
    return found


def to_dict(run: AgentRun) -> Dict:
    """序列化为 JSON 友好字典"""
    return {
        "question": run.question,
        "plan": run.plan,
        "final_answer": run.final_answer,
        "iterations": len(run.steps),
        "total_tokens": run.total_tokens,
        "duration_s": round(run.finished_at - run.started_at, 2),
        "steps": [
            {
                "iteration": s.iteration,
                "thought": s.thought,
                "action": s.action,
                "action_input": s.action_input,
                "observation_preview": s.observation[:200],
            }
            for s in run.steps
        ],
    }