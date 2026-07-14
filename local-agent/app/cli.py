"""交互式 CLI:在 PyCharm 里直接 run 就能对话

用法:
  PyCharm: 右键本文件 → Run 'cli'
  命令行:  cd ~/local-agent && /usr/local/bin/python3 -m app.cli
  命令行(单问题):  echo "echo hello" | python3 -m app.cli

可选参数(改顶部 CONSTANTS):
  - FRAMEWORK:  v1 / v2 / v3 / v4
  - MAX_HISTORY: 保留多少轮对话

特色:
  - 多轮会话(每轮带 history)
  - 实时显示 trace(thought/action/observation)
  - 流式:每一步都即时打印
  - 支持 /skills 列技能、/exit 退出、/clear 清屏
"""
import sys
import os
import json
import time
from typing import List, Dict

# 把项目根加到 path,保证 import 没问题(直接 run 本文件时)
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ============================================================
# 配置
# ============================================================
FRAMEWORK = "v1"     # v1=手写ReAct / v2=LangGraph / v3=autogen / v4=LangChain
MAX_HISTORY = 20     # 保留多少轮对话
SHOW_THINK = True    # 是否打印 thought
SHOW_OBS = True      # 是否打印 observation
VERBOSE = True       # trace 详细度


# ============================================================
# 工具函数
# ============================================================

def _color(text: str, code: str) -> str:
    """ANSI 颜色(Pycharm terminal 支持)"""
    return f"\033[{code}m{text}\033[0m"


def _step(action: str, action_input: dict, observation: str = "", thought: str = ""):
    """打印单步 trace"""
    if not VERBOSE:
        return
    print()
    if thought and SHOW_THINK:
        print(_color(f"💭 Thought: {thought[:200]}", "90"))  # 灰
    if action == "final":
        return
    args_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in action_input.items())
    print(_color(f"🔧 Action:  {action}({args_str})", "33"))  # 黄
    if observation and SHOW_OBS:
        obs_preview = observation[:300].replace("\n", "\n           ")
        print(_color(f"📋 Obs:     {obs_preview}", "36"))  # 青


def _ask_framework(question: str, history: List[Dict]) -> Dict:
    """根据 FRAMEWORK 调用对应的 loop"""
    if FRAMEWORK == "v1":
        from app.agent.loop import run
        r = run(question, history=history)
        d = {
            "framework": "v1-react",
            "final_answer": r.final_answer,
            "steps": [
                {
                    "iteration": s.iteration,
                    "thought": s.thought,
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation_preview": s.observation,
                }
                for s in r.steps
            ],
        }
        return d
    elif FRAMEWORK == "v2":
        from app.agent.loop_langgraph import run
        return run(question, history=history)
    elif FRAMEWORK == "v3":
        from app.agent.loop_autogen import run
        return run(question, history=history)
    elif FRAMEWORK == "v4":
        from app.agent.loop_langchain import run
        return run(question, history=history)
    else:
        raise ValueError(f"unknown framework: {FRAMEWORK}")


# ============================================================
# 主循环
# ============================================================

def chat_loop():
    """交互式对话循环"""
    history: List[Dict] = []

    # 启动 banner
    print(_color("=" * 60, "35"))
    print(_color(f"  Local Agent  (framework={FRAMEWORK})", "35"))
    print(_color("=" * 60, "35"))
    print(_color("命令:", "33"))
    print("  /skills        列出可用技能")
    print("  /history       打印当前会话历史")
    print("  /clear         清空会话历史")
    print("  /quit 或 /exit 退出")
    print()
    # 列技能
    try:
        from app.skills.registry import get_skill_names
        names = get_skill_names()
        print(_color(f"已注册 {len(names)} 个技能: {', '.join(names)}", "90"))
    except Exception as e:
        print(_color(f"加载技能失败: {e}", "31"))
    print()

    while True:
        try:
            user_input = input(_color("You > ", "32")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(_color("Bye!", "33"))
            break

        if not user_input:
            continue

        # 内置命令
        if user_input.startswith("/"):
            cmd = user_input[1:].lower().split()[0]
            if cmd in ("quit", "exit", "q"):
                print(_color("Bye!", "33"))
                break
            elif cmd == "skills":
                from app.skills.registry import get_skill_names
                for n in get_skill_names():
                    print(f"  - {n}")
                print()
                continue
            elif cmd == "history":
                print(_color(f"会话历史: {len(history)} 轮", "33"))
                for i, h in enumerate(history):
                    role = h.get("role", "?")
                    content = h.get("content", "")[:200]
                    print(f"  [{i}] {role}: {content}")
                print()
                continue
            elif cmd == "clear":
                history.clear()
                print(_color("已清空会话历史", "33"))
                continue
            elif cmd == "help":
                print(_color("命令: /skills /history /clear /quit", "33"))
                continue
            else:
                print(_color(f"未知命令: {user_input}", "31"))
                continue

        # 跑 agent
        t0 = time.time()
        try:
            result = _ask_framework(user_input, history)
        except Exception as e:
            print(_color(f"\n❌ Error: {type(e).__name__}: {e}", "31"))
            print()
            continue
        duration = time.time() - t0

        # 打印 trace
        steps = result.get("steps", [])
        for s in steps:
            _step(
                action=s.get("action", ""),
                action_input=s.get("action_input", {}),
                observation=s.get("observation_preview", s.get("observation", "")),
                thought=s.get("thought", ""),
            )

        # 最终答案
        final = result.get("final_answer", "(无答案)")
        fw = result.get("framework", FRAMEWORK)
        n_steps = len(steps)
        print()
        print(_color(f"🤖 Agent ({fw}, {n_steps} 步, {duration:.1f}s):", "35"))
        print(_color("─" * 60, "35"))
        print(final)
        print(_color("─" * 60, "35"))
        print()

        # 更新 history
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": final})
        # 滚动窗口
        if len(history) > MAX_HISTORY * 2:
            history = history[-(MAX_HISTORY * 2):]


def main():
    chat_loop()


if __name__ == "__main__":
    main()