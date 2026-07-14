"""测 LLM 调用(慢,真花钱)

跑法:
  /usr/local/bin/python3 -m pytest tests/test_llm_integration.py -v
  /usr/local/bin/python3 -m pytest tests/ -m "not slow" -v   # 跳过

文件命名以 _integration 结尾的话,默认不跑,需要显式 -k
"""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.mark.slow
def test_llm_basic_chat():
    """LLM 能响应一个简单问题"""
    from app.llm.client import chat
    r = chat([{"role": "user", "content": "1+1=?"}])
    assert r["content"]
    assert "2" in r["content"]


@pytest.mark.slow
def test_v1_real_loop():
    """v1 真跑一次单步任务"""
    from app.agent.loop import run
    r = run("echo 'hi from v1'")
    assert r.final_answer
    assert any(s.action == "run_shell" for s in r.steps)


@pytest.mark.slow
def test_v2_real_langgraph():
    """v2 LangGraph 真跑一次"""
    from app.agent.loop_langgraph import run
    d = run("echo 'hi from v2'")
    assert d["final_answer"]
    assert d["framework"] == "langgraph"


@pytest.mark.slow
def test_v4_real_langchain():
    """v4 LangChain Executor 真跑一次"""
    from app.agent.loop_langchain import run
    d = run("echo 'hi from v4'")
    assert d["framework"] == "langchain"
    # LangChain AgentExecutor 输出通常以 "Final Answer:" 开头
    assert d["final_answer"]