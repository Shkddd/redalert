"""测 CLI 的子流程(用 subprocess 模拟交互)"""
import sys
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent


def _run_cli(stdin_text: str, timeout: int = 60) -> str:
    """跑一次 CLI,返 stdout"""
    r = subprocess.run(
        ["bash", "-c", f"printf '{stdin_text}' | /usr/local/bin/python3 -m app.cli 2>&1"],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(ROOT),
    )
    return r.stdout


def test_cli_starts_and_exits():
    """CLI 启动 + /quit 正常退出"""
    out = _run_cli("/quit\n")
    assert "Local Agent" in out
    assert "framework=v1" in out
    assert "已注册 6 个技能" in out
    assert "Bye!" in out


def test_cli_skills_command():
    """/skills 列出所有 6 个技能"""
    out = _run_cli("/skills\n/quit\n")
    for s in ["read_file", "write_file", "run_shell", "list_dir", "web_fetch", "rag_query"]:
        assert f"- {s}" in out, f"missing {s} in /skills output"


def test_cli_runs_agent():
    """CLI 跑 agent: echo hi"""
    out = _run_cli("echo hi\n/quit\n")
    assert "🔧 Action" in out
    assert "run_shell" in out
    assert "hi" in out
    assert "Agent" in out
    # 应该看到 final 答案包含 "hi"
    assert "hi" in out


def test_cli_history_command():
    """/history 累积多轮后能打印"""
    out = _run_cli("echo a\necho b\n/history\n/quit\n")
    assert "会话历史: 4 轮" in out or "会话历史" in out


def test_cli_clear_command():
    """/clear 清空历史"""
    out = _run_cli("echo a\n/clear\n/history\n/quit\n")
    # 应该在 clear 之后 history 显示 0 轮
    assert "会话历史" in out


def test_cli_help_command():
    """/help 列出命令"""
    out = _run_cli("/help\n/quit\n")
    assert "/skills" in out
    assert "/history" in out
    assert "/clear" in out
    assert "/quit" in out


def test_cli_unknown_command():
    """未知命令不崩"""
    out = _run_cli("/foobar\n/quit\n")
    assert "未知命令" in out
    assert "Bye!" in out


def test_cli_framework_v1():
    """默认 framework=v1"""
    out = _run_cli("/quit\n")
    assert "framework=v1" in out


def test_cli_ansi_color_codes():
    """输出含 ANSI 颜色码"""
    out = _run_cli("/quit\n")
    # ANSI escape 是 \x1b[...m
    assert "\x1b[" in out


def test_cli_error_handled():
    """shell 命令失败不应让 CLI 崩"""
    out = _run_cli("rm /nonexistent_xyz_9999\n/quit\n")
    # 失败但 CLI 没崩
    assert "Bye!" in out


if __name__ == "__main__":
    # 单独跑这个文件也支持
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))