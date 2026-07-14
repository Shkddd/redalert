"""v2 - LangGraph StateGraph 实现 ReAct 循环

State: {messages, iteration, final_answer, steps}
Nodes:
  - llm_decide: LLM 决定下一步 (call_tool 或 finish)
  - call_tool:   执行工具,结果入 messages
  - finish:      收尾,提取 final_answer

Edges:
  llm_decide --(有 tool_call)--> call_tool --> llm_decide (循环)
  llm_decide --(无 tool_call / 超 max)--> finish

注意: langchain 顶层 import 会拉 datasets/huggingface 大依赖,
本文件用 lazy import 避免冷启动慢。
"""
import time
from typing import Annotated, List, Dict, Any
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from app.core.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, MAX_ITERATIONS
from app.skills.registry import get_tool_schemas, execute_skill, SKILL_REGISTRY


# ============================================================
# 1. LangChain Tool 包装
# ============================================================

def _build_lc_tools():
    """把我们的 SKILL_REGISTRY 包装成 LangChain Tool"""
    from langchain_core.tools import Tool
    tools = []
    for name, entry in SKILL_REGISTRY.items():
        fn = entry["fn"]
        desc = entry["schema"]["description"]
        t = Tool(name=name, func=fn, description=desc)
        tools.append(t)
    return tools


# ============================================================
# 2. State 定义
# ============================================================

class AgentState(TypedDict):
    """LangGraph 状态"""
    messages: Annotated[List, add_messages]
    iteration: int
    steps: List[Dict]
    final_answer: str


SYSTEM_PROMPT = """你是一个 Agentic 助手,通过循环调用工具解决问题。

工作模式: 分析 → 选工具 → 执行 → 看结果 → 决定下一步 → 收尾

规则:
- 一次只调一个工具
- 拿到工具结果后再决定下一步
- 重要信息记下来
- 当前用户: macOS, home=/Users/lix
- 路径用绝对路径
- 信息够用就用自然语言给 final answer,不再调工具
"""


# ============================================================
# 3. 节点函数
# ============================================================

def make_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0.3,
        max_tokens=4096,
    ).bind_tools(_build_lc_tools())


_llm = None
def get_llm():
    global _llm
    if _llm is None:
        _llm = make_llm()
    return _llm


def llm_decide(state: AgentState) -> AgentState:
    """节点 1: LLM 决策下一步"""
    from langchain_core.messages import SystemMessage
    llm = get_llm()
    msgs = state["messages"]
    if not msgs or not isinstance(msgs[0], SystemMessage):
        msgs = [SystemMessage(content=SYSTEM_PROMPT)] + list(msgs)
        state["messages"] = msgs
    resp = llm.invoke(msgs)
    return {
        "messages": [resp],
        "iteration": state.get("iteration", 0) + 1,
        "steps": state.get("steps", []),
        "final_answer": state.get("final_answer", ""),
    }


def call_tool(state: AgentState) -> AgentState:
    """节点 2: 执行 LLM 调用的工具"""
    from langchain_core.messages import AIMessage, ToolMessage
    last = state["messages"][-1]
    new_messages = []
    new_steps = list(state.get("steps", []))

    for tc in (last.tool_calls or []):
        name = tc["name"]
        args = tc["args"]
        try:
            result = LC_TOOLS_BY_NAME[name].invoke(args)
            if not isinstance(result, str):
                import json
                result = json.dumps(result, ensure_ascii=False)
        except Exception as e:
            result = f"Error: {type(e).__name__}: {e}"

        new_steps.append({
            "iteration": state.get("iteration", 0),
            "action": name,
            "action_input": args,
            "observation_preview": str(result)[:200],
            "timestamp": time.time(),
        })
        new_messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    return {
        "messages": new_messages,
        "steps": new_steps,
    }


def should_continue(state: AgentState) -> str:
    """条件边: 决定是继续调工具还是结束"""
    from langchain_core.messages import AIMessage
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return "finish"
    last = state["messages"][-1] if state["messages"] else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "call_tool"
    return "finish"


def finish(state: AgentState) -> AgentState:
    """节点 3: 收尾,提取 final answer"""
    from langchain_core.messages import AIMessage
    last = state["messages"][-1] if state["messages"] else None
    final = last.content if isinstance(last, AIMessage) else str(last)
    return {
        "final_answer": final or "(空回答)",
        "steps": state.get("steps", []),
    }


# ============================================================
# 4. 构建 graph
# ============================================================

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("llm_decide", llm_decide)
    g.add_node("call_tool", call_tool)
    g.add_node("finish", finish)
    g.add_edge(START, "llm_decide")
    g.add_conditional_edges("llm_decide", should_continue, {
        "call_tool": "call_tool",
        "finish": "finish",
    })
    g.add_edge("call_tool", "llm_decide")
    g.add_edge("finish", END)
    return g.compile()


# 编译一次,复用
_GRAPH = None
def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


# ============================================================
# 5. 公开入口
# ============================================================

def run(question: str, history: List[Dict] = None) -> Dict:
    """跑一次 LangGraph agent,返回 trace dict"""
    from langchain_core.messages import HumanMessage, AIMessage
    graph = get_graph()
    msgs = []
    if history:
        for h in history:
            if h.get("role") == "user":
                msgs.append(HumanMessage(content=h["content"]))
            elif h.get("role") == "assistant":
                msgs.append(AIMessage(content=h["content"]))
    msgs.append(HumanMessage(content=question))

    init_state: AgentState = {
        "messages": msgs,
        "iteration": 0,
        "steps": [],
        "final_answer": "",
    }
    t0 = time.time()
    final_state = graph.invoke(init_state)
    duration = time.time() - t0

    return {
        "framework": "langgraph",
        "question": question,
        "final_answer": final_state.get("final_answer", ""),
        "iterations": final_state.get("iteration", 0),
        "duration_s": round(duration, 2),
        "steps": final_state.get("steps", []),
    }


# module-level 缓存
LC_TOOLS = _build_lc_tools()
LC_TOOLS_BY_NAME = {t.name: t for t in LC_TOOLS}