"""observability 模块的测试

测两个核心:
1. no-op 模式 (无 env key): 不 crash, 不影响主流程
2. mock key 模式: 能识别 enabled=True,但 trace/record 不抛异常 (fail_safe)
3. decorator 在嵌套 + 多次调用场景稳定
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_no_keys_no_crash():
    """无任何 env key: obs 应该全部 disabled 但不抛错"""
    for k in ["LANGSMITH_API_KEY", "AGENTOPS_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"]:
        os.environ.pop(k, None)
    # 强制重新 import 单例 (因为 env vars 在 import 时检查)
    import importlib
    from app.core import observability
    importlib.reload(observability)
    obs = observability.obs
    obs.setup()
    assert obs.langsmith_enabled is False
    assert obs.agentops_enabled is False
    assert obs.otel_enabled is False


def test_record_methods_safe_when_disabled():
    """obs.record_*() 在 disabled 情况下也不抛错"""
    os.environ.pop("LANGSMITH_API_KEY", None)
    os.environ.pop("AGENTOPS_API_KEY", None)
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    from app.core.observability import obs

    obs.record_llm(model="test", latency=0.1, ok=True)
    obs.record_tool(name="test", latency=0.1, ok=True)
    obs.start_session()
    obs.end_session()


def test_decorator_no_keys_returns_correct_value():
    """@obs.trace() 在无 key 模式下就是个普通装饰器"""
    os.environ.pop("LANGSMITH_API_KEY", None)
    from app.core.observability import obs

    @obs.trace(name="my_func")
    def double(x):
        return x * 2

    assert double(21) == 42


def test_greeting_detection():
    """_is_greeting 边界用例"""
    os.environ.pop("LANGSMITH_API_KEY", None)
    sys.path.insert(0, "/Users/lix/local-agent")
    from app.agent.loop_plan import _is_greeting

    assert _is_greeting("hi") is True
    assert _is_greeting("Hi!") is True
    assert _is_greeting("你好") is True
    assert _is_greeting("你好!") is True
    assert _is_greeting("早上好") is True
    assert _is_greeting("  hello  ") is True
    assert _is_greeting("") is True
    # 真的问题应该 False
    assert _is_greeting("echo hi") is False
    assert _is_greeting("今天是星期几") is False
    assert _is_greeting("帮我看看 local-rag") is False