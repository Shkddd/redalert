"""v3 - autogen GroupChat 多 agent 协同

角色:
  - Planner:   拿到用户问题,拆解为子任务
  - Executor:  调工具执行子任务
  - Verifier:  验证 Executor 的结果,决定继续还是收尾
  - UserProxy: 代替用户,自动执行工具

autogen 0.7+ 用新 API: AssistantAgent + RoundRobinGroupChat
"""
import asyncio
import time
import json
from typing import Dict, List, Any

from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.tools import FunctionTool

from app.core.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, MAX_ITERATIONS
from app.skills.registry import execute_skill, SKILL_REGISTRY


# ============================================================
# 1. 把 SKILL_REGISTRY 转成 autogen FunctionTool
# ============================================================

def _build_autogen_tools() -> List[FunctionTool]:
    tools = []
    for name, entry in SKILL_REGISTRY.items():
        fn = entry["fn"]
        desc = entry["schema"]["description"]
        params = entry["schema"].get("parameters", {}).get("properties", {})
        # 构造一个 schema dict 给 FunctionTool
        schema = {
            "type": "object",
            "properties": params,
            "required": entry["schema"].get("parameters", {}).get("required", []),
        }
        # autogen FunctionTool 的 from_func 接受任意函数 + 描述
        ft = FunctionTool(
            func=fn,
            name=name,
            description=desc,
        )
        tools.append(ft)
    return tools


AUTOGEN_TOOLS = _build_autogen_tools()


# ============================================================
# 2. Model client
# ============================================================

def get_model_client():
    return OpenAIChatCompletionClient(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True,
            "family": "unknown",
        },
    )


# ============================================================
# 3. 角色 prompt
# ============================================================

PLANNER_SYS = """你是 Planner。职责:
1. 拿到用户问题,拆解为清晰的子任务
2. 决定每个子任务需要哪个工具
3. 不直接执行工具,告诉 Executor 下一步该做什么
4. 看到 Executor 完成后,总结是否所有子任务完成
5. 全部完成时输出 'TASK COMPLETE' 收尾

注意: 你的输出会被 Executor 看到,要明确告诉它调用什么工具、传什么参数。
"""

EXECUTOR_SYS = """你是 Executor。职责:
1. 拿到 Planner 的指令,调用工具
2. 把工具结果回给 Planner
3. 一次只调一个工具
4. 当前用户: macOS, home=/Users/lix,~ 展开到 /Users/lix
5. 路径用绝对路径

工具会自动提供给你。
"""

VERIFIER_SYS = """你是 Verifier。职责:
1. 检查 Executor 的工具结果是否推进了任务
2. 若结果符合预期,告诉 Planner "可以收尾"
3. 若结果不对或不够,告诉 Planner 需要补充什么

注意: 简洁判断,3 句话内给结论。
"""


# ============================================================
# 4. 主流程
# ============================================================

def _sync_run(coro):
    """autogen 是 async,在同步 FastAPI 上下文里跑"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已在 async 上下文,另开线程
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        pass
    return asyncio.run(coro)


async def _arun(question: str) -> Dict:
    model = get_model_client()

    planner = AssistantAgent(
        name="Planner",
        system_message=PLANNER_SYS,
        model_client=model,
    )
    executor = AssistantAgent(
        name="Executor",
        system_message=EXECUTOR_SYS,
        model_client=model,
        tools=AUTOGEN_TOOLS,
    )
    verifier = AssistantAgent(
        name="Verifier",
        system_message=VERIFIER_SYS,
        model_client=model,
    )

    # RoundRobin: Planner → Executor → Verifier → Planner → ...
    team = RoundRobinGroupChat(
        participants=[planner, executor, verifier],
        termination_condition=MaxMessageTermination(max_messages=MAX_ITERATIONS * 2),
        max_turns=MAX_ITERATIONS * 2,
    )

    t0 = time.time()
    result = await team.run(task=question)
    duration = time.time() - t0

    # 解析 messages 为 steps
    steps = []
    final_answer = ""
    for m in result.messages:
        src = getattr(m, "source", "")
        content = getattr(m, "content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        if src == "Executor":
            # 工具调用一般体现在 content 描述里
            steps.append({
                "role": src,
                "content": str(content)[:300],
            })
        if src == "Planner" and ("TASK COMPLETE" in str(content) or not final_answer):
            if "TASK COMPLETE" in str(content):
                final_answer = str(content).replace("TASK COMPLETE", "").strip()

    # 如果没收到 TASK COMPLETE,取最后一条 Planner 内容
    if not final_answer:
        for m in reversed(result.messages):
            if getattr(m, "source", "") == "Planner":
                final_answer = str(getattr(m, "content", ""))
                break

    return {
        "framework": "autogen",
        "question": question,
        "final_answer": final_answer or "(无明确收尾)",
        "iterations": len([m for m in result.messages if getattr(m, "source", "") in ("Planner", "Executor", "Verifier")]),
        "duration_s": round(duration, 2),
        "steps": steps[-20:],   # 截最后 20 步
        "raw_messages": [
            {
                "source": getattr(m, "source", ""),
                "content": str(getattr(m, "content", ""))[:500],
            }
            for m in result.messages
        ],
    }


def run(question: str, history: List[Dict] = None) -> Dict:
    """同步入口"""
    # history 暂不传给 autogen(简化为单轮)
    return _sync_run(_arun(question))