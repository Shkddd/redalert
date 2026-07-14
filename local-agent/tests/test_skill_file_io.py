"""测 read_file / write_file / list_dir(纯本地,不需要 LLM)"""
import sys, os, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.skills.registry import execute_skill


def _tmpfile(content="hello world") -> str:
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.write(fd, content.encode())
    os.close(fd)
    return path


def test_write_then_read():
    """write 写完,read 能读回来"""
    p = _tmpfile()
    try:
        r = execute_skill("write_file", {"path": p, "content": "agent test content"})
        assert r["bytes_written"] > 0

        r = execute_skill("read_file", {"path": p})
        assert "agent test content" in r["text"]
    finally:
        os.remove(p)


def test_read_file_not_found():
    """不存在的文件应该报错不崩"""
    r = execute_skill("read_file", {"path": "/tmp/nonexistent_xyz_12345.txt"})
    assert "error" in r or "not found" in str(r).lower()


def test_read_file_max_chars():
    """max_chars 截断"""
    p = _tmpfile("a" * 1000)
    try:
        r = execute_skill("read_file", {"path": p, "max_chars": 50})
        assert len(r["text"]) <= 50
    finally:
        os.remove(p)


def test_list_dir():
    """列 /tmp 至少有 entries"""
    r = execute_skill("list_dir", {"path": "/tmp"})
    assert "entries" in r
    assert isinstance(r["entries"], list)
    assert len(r["entries"]) > 0


def test_list_dir_invalid_path():
    """不存在的目录应该报错不崩"""
    r = execute_skill("list_dir", {"path": "/tmp/__nope_zzz_9999__"})
    assert "error" in r or "entries" in r


def test_write_file_mode():
    """append 模式追加"""
    p = _tmpfile("line1\n")
    try:
        execute_skill("write_file", {"path": p, "content": "line2\n", "mode": "append"})
        with open(p) as f:
            content = f.read()
        assert "line1" in content and "line2" in content
    finally:
        os.remove(p)