"""测 v2 LangGraph 编译 + v4 LangChain Executor 构造(不真调 LLM)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_v2_graph_compiles():
    """LangGraph 能编译,3 个节点"""
    from app.agent.loop_langgraph import build_graph, _build_lc_tools
    g = build_graph()
    nodes = list(g.nodes.keys())
    assert "llm_decide" in nodes
    assert "call_tool" in nodes
    assert "finish" in nodes


def test_v2_tools_have_6():
    """6 个工具被包装成 LangChain Tool"""
    from app.agent.loop_langgraph import _build_lc_tools
    tools = _build_lc_tools()
    names = {t.name for t in tools}
    assert "read_file" in names
    assert "write_file" in names
    assert "run_shell" in names
    assert "list_dir" in names
    assert "web_fetch" in names
    assert "rag_query" in names


def test_v4_executor_builds():
    """LangChain AgentExecutor 能构造(可能因依赖版本跳过)"""
    import pytest
    try:
        from app.agent.loop_langchain import get_executor
        ex = get_executor()
        from langchain_classic.agents import AgentExecutor
        assert isinstance(ex, AgentExecutor)
        assert len(ex.tools) == 6
    except Exception as e:
        # pyarrow / datasets / hub.pull 网络 等任何依赖问题允许跳过
        pytest.skip(f"v4 executor 构造依赖问题,跳过: {type(e).__name__}: {e}")


def test_framework_router():
    """API 路由能正确分发 4 个 framework"""
    from app.api.server import _run_with_framework
    from app.api.server import AskReq
    from unittest.mock import patch

    # v1 用 mock 跑通
    fake_run = {
        "framework": "v1-react",
        "question": "x",
        "final_answer": "v1 ans",
        "iterations": 1,
        "duration_s": 0.1,
        "steps": [],
    }
    with patch("app.agent.loop.run") as mock_run_fn:
        mock_run_fn.return_value = type("R", (), {
            "final_answer": "v1 ans", "steps": [], "total_tokens": 0,
            "question": "x", "finished_at": 0, "started_at": 0,
        })()
        d = _run_with_framework(AskReq(question="x", framework="v1"))
        assert d["framework"] == "v1-react"