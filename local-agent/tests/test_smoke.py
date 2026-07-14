"""测基础工具(不调 LLM,纯函数)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import LLM_MODEL, LLM_BASE_URL, MAX_ITERATIONS, BASE_DIR
from app.skills.registry import get_skill_names, get_tool_schemas


def test_config_basic():
    """配置项能读到"""
    assert LLM_MODEL, "LLM_MODEL 未配置"
    assert LLM_BASE_URL.startswith("http")
    assert MAX_ITERATIONS >= 1
    assert BASE_DIR.exists()


def test_skills_registered():
    """至少 5 个基础技能注册了"""
    names = get_skill_names()
    assert "read_file" in names
    assert "write_file" in names
    assert "run_shell" in names
    assert "list_dir" in names
    assert "web_fetch" in names
    assert "rag_query" in names


def test_tool_schemas_valid():
    """每个技能 schema 有 name/description/parameters"""
    schemas = get_tool_schemas()
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert len(s["description"]) > 5
        assert "parameters" in s
        assert "properties" in s["parameters"]


def test_ask_req_framework_field():
    """API 接受 framework 字段"""
    from app.api.server import AskReq
    req = AskReq(question="hello", framework="v2")
    assert req.framework == "v2"