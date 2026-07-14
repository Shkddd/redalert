# Local Agent

Agentic 循环框架,同一套 skill 库跑通 **4 种实现**对比:
  · **v1** 手写 ReAct 循环 (loop.py)
  · **v2** LangGraph StateGraph (loop_langgraph.py)
  · **v3** autogen RoundRobinGroupChat Planner/Executor/Verifier (loop_autogen.py)
  · **v4** LangChain AgentExecutor + ReAct prompt (loop_langchain.py)

## 启动

```bash
cd ~/local-agent
pip3 install --user -r requirements.txt
```

**选项 A：交互式 CLI(PyCharm 里推荐)**
```bash
# PyCharm: 右键 app/cli.py → Run 'cli'
# 命令行:
/usr/local/bin/python3 -m app.cli
```
支持多轮对话、内置命令 (`/skills` `/history` `/clear` `/quit`)、实时 trace。

**选项 B：Web UI**
```bash
/usr/local/bin/python3 -m uvicorn app.api.server:app --port 8001 --reload
```
打开 http://localhost:8001,聊天框里选 framework (v1/v2/v3/v4) + 输入问题。

## 4 个框架路由

| 框架 | 入口文件 | 适合 |
|-----|---------|-----|
| v1 手写 | app/agent/loop.py | 学习 / 完全可控 |
| v2 LangGraph | app/agent/loop_langgraph.py | 节点可视化 / LangSmith trace |
| v3 autogen | app/agent/loop_autogen.py | 多 agent 角色协作 / 验证 |
| v4 LangChain | app/agent/loop_langchain.py | LangChain 生态(Retrievers/VectorStores) |

## 单元测试

```bash
cd ~/local-agent
/usr/local/bin/python3 -m pytest tests/ -v                 # 全跑(默认 skip slow)
/usr/local/bin/python3 -m pytest tests/ -m slow -v         # 只跑 LLM 集成测试(会花钱)
/usr/local/bin/python3 -m pytest tests/test_v1_loop.py -v  # 单跑某条链路
/usr/local/bin/python3 -m pytest tests/ -k "read_file" -v  # 按名字匹配
```

测试分层:
  - test_smoke.py              基础配置 + 技能注册
  - test_skill_run_shell.py    shell 技能
  - test_skill_file_io.py      文件读写技能
  - test_pseudo_tool_calls.py  伪 tool_call 解析(minimax hack)
  - test_v1_loop.py            v1 循环(用 mock 不真调 LLM)
  - test_v2_v4_frameworks.py   v2/v4 graph + executor 构造
  - test_llm_integration.py    真调 LLM(标 slow,默认 skip)

## 项目结构

```
app/
├── api/server.py        # FastAPI 入口,4 个 framework 路由分发
├── llm/client.py        # OpenAI 兼容 LLM 客户端
├── core/config.py       # 配置(.env 读 key)
├── skills/registry.py   # 6 个基础技能 + schema
└── agent/
    ├── loop.py          # v1 手写 ReAct
    ├── loop_langgraph.py# v2 LangGraph
    ├── loop_autogen.py  # v3 autogen GroupChat
    └── loop_langchain.py# v4 LangChain AgentExecutor
```

## 环境

- macOS + Python 3.11
- LLM: minimax-cn (OpenAI 兼容),key 走 `~/.hermes/.env` 的 `MINIMAX_CN_API_KEY`
[1] 规划(可选)：LLM 看问题,出 Plan
   ↓
[2] ReAct 循环(最多 15 轮)
   ├─ THINK: LLM 看 history,选下一步
   ├─ ACT: 调用技能
   ├─ OBSERVE: 结果入 history
   └─ VERIFY: 隐式(下一轮决策体现)
   ↓
[3] 收尾：LLM 出 final answer
```

## 内置技能(6 个)

| 技能 | 用途 |
|------|------|
| `read_file` | 读本地文件 |
| `write_file` | 写本地文件 |
| `run_shell` | 执行 shell 命令 |
| `list_dir` | 列目录 |
| `web_fetch` | HTTP GET / 抓网页 |
| `rag_query` | 查 local-rag 服务 |

## 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 聊天 UI |
| `/api/ask` | POST | 同步(返回完整 trace) |
| `/api/ask/stream` | POST | 流式(SSE,实时推送 thought/action/observation) |
| `/api/skills` | GET | 列可用技能 |
| `/api/sessions` | GET | 列会话 |

## 跑示例

```bash
# 1. CLI 跑一次
python3 -c "
from app.agent.loop import run
r = run('列出 ~/local-rag 目录的 Python 文件,然后用 read_file 看 main.py 的内容,总结一下这个项目')
import json
print(json.dumps({
    'final': r.final_answer[:200],
    'iterations': len(r.steps),
    'steps': [(s.action, list(s.action_input.keys())) for s in r.steps]
}, ensure_ascii=False, indent=2))
"
```

## 加新技能

在 `app/skills/registry.py` 加一个 Python 函数 + 一段 JSON schema,加进 `SKILL_REGISTRY` 字典即可。重启服务后 LLM 自动发现。

## 跑通 RAG 联动

```bash
# 终端 1: 起 RAG
cd ~/local-rag && uvicorn app.main:app --port 8000

# 终端 2: 起 Agent
cd ~/local-agent && uvicorn app.api.server:app --port 8001

# 在 UI 问: "公司应收账款政策是什么?"
# → agent 会自己调 rag_query 拿答案
```