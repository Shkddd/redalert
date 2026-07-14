"""v4 - LangChain AgentExecutor (经典 ReAct 风格)

跟 v2 LangGraph 的区别:
  - v2 (LangGraph)  显式 StateGraph,节点+边可视化
  - v4 (AgentExec)  LangChain 老牌入口,内部用 ReAct prompt 模板,更"开箱即用"

适合: 想要 LangChain 生态的 Tools/Retrievers/VectorStores 时
"""
import time
from typing import Dict, List
from langchain_core.tools import Tool

from app.core.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, MAX_ITERATIONS
from app.agent.loop_langgraph import _build_lc_tools
from app.skills.registry import SKILL_REGISTRY


SYSTEM_PROMPT = """You are an Agentic assistant. Use tools to solve problems step by step.

Rules:
- One tool call at a time
- Think before acting (Thought/Action/Action Input/Observation)
- Stop when you have enough info
- Use absolute paths (current user: macOS, home=/Users/lix)
"""


def _build_executor():
    """懒加载 langchain 链,避免顶层 import datasets/huggingface 拖慢"""
    from langchain_classic.agents import AgentExecutor, create_react_agent
    from langchain_openai import ChatOpenAI
    from langchain import hub
    llm = ChatOpenAI(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0.3,
    )
    tools = _build_lc_tools()
    # 用 LangChain Hub 拉 ReAct prompt
    try:
        prompt = hub.pull("hwchase17/react")
    except Exception:
        # Hub 拉不下来,自己拼一个简化版
        from langchain_core.prompts import PromptTemplate
        template = """Answer the following questions as best you can. You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought:{agent_scratchpad}"""
        prompt = PromptTemplate.from_template(template)

    agent = create_react_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        max_iterations=MAX_ITERATIONS,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        verbose=False,
    )


_EXECUTOR = None
def get_executor():
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = _build_executor()
    return _EXECUTOR


def run(question: str, history: List[Dict] = None) -> Dict:
    """跑一次 LangChain AgentExecutor,返回 trace"""
    # history 转成对话上下文(简单 prefix 进去)
    full_q = question
    if history:
        prefix = "\n".join(
            f"{h['role']}: {h['content']}" for h in history[-4:]
        )
        full_q = f"{prefix}\nuser: {question}"

    t0 = time.time()
    exec_ = get_executor()
    try:
        result = exec_.invoke({"input": full_q})
        final = result.get("output", "")
        error = None
    except Exception as e:
        final = f"[AgentExec Error: {type(e).__name__}: {e}]"
        result = {}
        error = str(e)
    duration = time.time() - t0

    # 解析 intermediate_steps 为 trace
    steps = []
    for i, (action, obs) in enumerate(result.get("intermediate_steps", []), 1):
        steps.append({
            "iteration": i,
            "action": action.tool,
            "action_input": action.tool_input,
            "observation_preview": str(obs)[:200],
        })

    return {
        "framework": "langchain",
        "question": question,
        "final_answer": final,
        "iterations": len(steps),
        "duration_s": round(duration, 2),
        "steps": steps,
        "error": error,
    }