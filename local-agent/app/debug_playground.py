"""PyCharm debug 入口:单文件调 4 个 framework,断点直接命中

用法 (PyCharm 里):
  1. 打开本文件
  2. 在下面某个 framework 函数里想断点的那一行左边点击
  3. 右键某个 debug_xxx() -> Debug 'debug_xxx'
  4. 看 Variables / Watches 面板里的 state / messages / final_answer

命令行:
  /usr/local/bin/python3 -m app.debug_playground              # 默认跑 v1
  /usr/local/bin/python3 -m app.debug_playground --fw v2     # 跑 LangGraph
  /usr/local/bin/python3 -m app.debug_playground --fw v4     # 跑 LangChain
  /usr/local/bin/python3 -m app.debug_playground --q "ls -la ~/local-rag | head -3"

每个 framework 函数都是独立 entry point,你可以单独 debug。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# 4 个 framework 入口,想断哪个就断哪个
# ============================================================

def debug_v1_react(question: str = "echo hello from v1"):
    """v1: 手写 ReAct 循环。断点建议:
    - app/agent/loop.py 里 `while it < MAX_ITERATIONS:`  (主循环入口)
    - `_extract_pseudo_tool_calls()` 调用处             (伪 tool_call 解析)
    - `resp = chat(messages, ...)` 那行                  (看 LLM 返回)
    """
    from app.agent.loop import run, to_dict
    print(f"\n>>> v1 手写 ReAct: {question}")
    result = run(question)
    d = to_dict(result)
    print(f"    iterations={d['iterations']}, duration={d['duration_s']}s")
    print(f"    final: {d['final_answer'][:200]}")
    return d


def debug_v2_langgraph(question: str = "echo hello from v2"):
    """v2: LangGraph StateGraph。断点建议:
    - app/agent/loop_langgraph.py 里 `graph.compile()` 后那行    (图编译)
    - `make_llm_decide_node()` 内部 `chat(messages)` 调用处       (决策节点)
    - `make_tool_call_node()` 内部 `execute_skill()` 处          (工具执行)
    """
    from app.agent.loop_langgraph import run as run_lg
    print(f"\n>>> v2 LangGraph StateGraph: {question}")
    d = run_lg(question)
    print(f"    iterations={d.get('iterations')}, duration={d.get('duration_s')}s")
    print(f"    final: {d.get('final_answer', '')[:200]}")
    return d


def debug_v3_autogen(question: str = "echo hello from v3"):
    """v3: autogen GroupChat。断点建议:
    - app/agent/loop_autogen.py 里 `GroupChat(agents=[...])`         (群聊构造)
    - `_user_proxy_initiate_chat()` 内部                            (启动 chat)
    - `agent.generate_reply()` 内部 (实际 LLM 调用)                   (单回合决策)
    """
    from app.agent.loop_autogen import run as run_ag
    print(f"\n>>> v3 autogen GroupChat: {question}")
    print("    (autogen 内部循环,断点放在 agent.generate_reply)")
    d = run_ag(question)
    print(f"    iterations={d.get('iterations')}, duration={d.get('duration_s')}s")
    print(f"    final: {d.get('final_answer', '')[:200]}")
    return d


def debug_v4_langchain(question: str = "echo hello from v4"):
    """v4: LangChain AgentExecutor。断点建议:
    - app/agent/loop_langchain.py 里 `AgentExecutor.from_agent_and_tools()` (构造 executor)
    - `executor.invoke(input=...)` 那行                                (实际 invoke)
    - `_iter_next_step()` 内部 `agent.plan(...)`                      (LLM 决策)
    """
    from app.agent.loop_langchain import run as run_lc
    print(f"\n>>> v4 LangChain AgentExecutor: {question}")
    d = run_lc(question)
    print(f"    iterations={d.get('iterations')}, duration={d.get('duration_s')}s")
    print(f"    final: {d.get('final_answer', '')[:200]}")
    return d


# ============================================================
# 主入口:命令行跑选哪个 framework
# ============================================================

FRAMEWORKS = {
    "v1": debug_v1_react,
    "v2": debug_v2_langgraph,
    "v3": debug_v3_autogen,
    "v4": debug_v4_langchain,
}


def main():
    parser = argparse.ArgumentParser(description="PyCharm debug playground")
    parser.add_argument("--fw", "--framework", default="v1", choices=list(FRAMEWORKS.keys()),
                        help="哪个 framework (v1/v2/v3/v4)")
    parser.add_argument("--q", default=None,
                        help="用户问题 (默认每个 framework 自带 sample)")
    args = parser.parse_args()

    fn = FRAMEWORKS[args.fw]
    result = fn(args.q) if args.q else fn()
    return result


if __name__ == "__main__":
    main()
