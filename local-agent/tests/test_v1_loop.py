"""测 v1 loop 的 run() 函数(不真调 LLM,patch 掉 client.chat)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch
from app.agent import loop as loop_mod


def test_v1_run_simple_fact():
    """LLM 直接给 final,1 步就收尾"""
    fake = {"content": "2+2=4", "tool_calls": [], "_usage": {}}
    with patch.object(loop_mod, "chat", return_value=fake):
        run = loop_mod.run("2+2=?", history=[])
    assert run.final_answer == "2+2=4"
    assert len(run.steps) == 1
    assert run.steps[0].action == "final"


def test_v1_run_with_tool_call():
    """LLM 先调工具再 final,2 步"""
    fake1 = {
        "content": "",
        "tool_calls": [{"id": "1", "name": "run_shell", "arguments": {"command": "echo hi"}}],
        "_usage": {},
    }
    fake2 = {"content": "shell 输出是 hi", "tool_calls": [], "_usage": {}}
    with patch.object(loop_mod, "chat", side_effect=[fake1, fake2]):
        run = loop_mod.run("echo 一下 hi", history=[])
    assert run.final_answer == "shell 输出是 hi"
    assert len(run.steps) == 2
    assert run.steps[0].action == "run_shell"
    assert "hi" in run.steps[0].observation


def test_v1_run_pseudo_tool_call():
    """LLM 在 text 里写伪 tool_call,也能识别并执行"""
    fake = {
        "content": '我先 run_shell({"command": "echo aha"})',
        "tool_calls": [],
        "_usage": {},
    }
    fake2 = {"content": "好的输出 aha", "tool_calls": [], "_usage": {}}
    with patch.object(loop_mod, "chat", side_effect=[fake, fake2]):
        run = loop_mod.run("echo 一下 aha", history=[])
    assert run.final_answer == "好的输出 aha"
    assert any(s.action == "run_shell" for s in run.steps)


def test_v1_run_max_iterations():
    """LLM 一直调工具不收尾,达到上限应自动结束"""
    fake = {
        "content": "",
        "tool_calls": [{"id": "1", "name": "run_shell", "arguments": {"command": "echo x"}}],
        "_usage": {},
    }
    # 调 20 次(超过默认 15 上限)
    with patch.object(loop_mod, "chat", return_value=fake):
        run = loop_mod.run("无限循环", history=[])
    assert "已达" in run.final_answer or "上限" in run.final_answer
    assert len(run.steps) > 0


def test_v1_run_llm_error():
    """LLM 调用失败,不崩,给 fallback 答案"""
    def boom(*a, **kw):
        raise RuntimeError("network down")
    with patch.object(loop_mod, "chat", side_effect=boom):
        run = loop_mod.run("hi", history=[])
    assert "LLM 调用失败" in run.final_answer or "RuntimeError" in run.final_answer


def test_to_dict_shape():
    """to_dict 输出包含所有必要字段"""
    run = loop_mod.run("1+1", history=[])
    d = loop_mod.to_dict(run)
    for k in ("question", "final_answer", "iterations", "duration_s", "steps"):
        assert k in d