"""测 v1 loop 的伪 tool_call 解析(minimax 模型的兼容 hack)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.loop import _extract_pseudo_tool_calls
from app.skills.registry import get_tool_schemas


SCHEMAS = get_tool_schemas()


def test_parse_pseudo_json():
    """LLM 写 run_shell({"command": "ls"}) 也能解析"""
    text = '我先 ls 一下:\nrun_shell({"command": "ls /tmp"})'
    calls = _extract_pseudo_tool_calls(text, SCHEMAS)
    assert len(calls) == 1
    assert calls[0]["name"] == "run_shell"
    assert calls[0]["arguments"]["command"] == "ls /tmp"


def test_parse_pseudo_single_quotes():
    """单引号 JSON 也能解析"""
    text = "read_file({'path': '/tmp/test.txt'})"
    calls = _extract_pseudo_tool_calls(text, SCHEMAS)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"


def test_parse_pseudo_multiple():
    """多次调用都能识别"""
    text = """step1: list_dir({"path": "/tmp"})
step2: read_file({"path": "/tmp/foo.txt"})"""
    calls = _extract_pseudo_tool_calls(text, SCHEMAS)
    names = [c["name"] for c in calls]
    assert "list_dir" in names
    assert "read_file" in names


def test_parse_no_call():
    """纯文字不抽"""
    text = "这是普通中文,没有工具调用"
    calls = _extract_pseudo_tool_calls(text, SCHEMAS)
    assert calls == []


def test_parse_dedup():
    """同名字只取一次(避免 LLM 重复写)"""
    text = 'run_shell({"command": "ls"}) 我再想想...\nrun_shell({"command": "ls"})'
    calls = _extract_pseudo_tool_calls(text, SCHEMAS)
    assert len(calls) == 1


def test_parse_ignore_unknown():
    """不在工具列表里的函数名忽略"""
    text = 'evil_call({"x": 1})  read_file({"path": "/x"})'
    calls = _extract_pseudo_tool_calls(text, SCHEMAS)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"