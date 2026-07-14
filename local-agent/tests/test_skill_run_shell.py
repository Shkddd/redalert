"""测 run_shell 技能(纯本地执行,不调 LLM)"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.skills.registry import execute_skill


def test_run_shell_echo():
    """echo 应该能跑通"""
    r = execute_skill("run_shell", {"command": "echo hello"})
    assert r["exit_code"] == 0
    assert "hello" in r["stdout"]


def test_run_shell_ls_tmp():
    """ls /tmp 至少 1 行"""
    r = execute_skill("run_shell", {"command": "ls /tmp | head -3"})
    assert r["exit_code"] == 0
    assert r["stdout"].strip() != ""


def test_run_shell_fail():
    """故意跑一个不存在的命令,exit_code != 0"""
    r = execute_skill("run_shell", {"command": "false"})
    assert r["exit_code"] != 0


def test_run_shell_truncation():
    """超长输出应该被截断"""
    r = execute_skill("run_shell", {"command": "yes | head -10000"})
    assert r["exit_code"] == 0
    assert r.get("truncated") is True


def test_run_shell_timeout():
    """sleep 超过 timeout 应该被 kill"""
    r = execute_skill("run_shell", {"command": "sleep 10", "timeout": 2})
    # timeout 时返回 {"error": ...},正常时返回 {"exit_code": ...}
    assert r.get("exit_code") != 0 or "timeout" in str(r).lower()