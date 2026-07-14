"""单测脚手架

跑测试:
  cd ~/local-agent
  /usr/local/bin/python3 -m pytest tests/ -v                  # 全跑
  /usr/local/bin/python3 -m pytest tests/test_skill_run_shell.py -v  # 单跑
  /usr/local/bin/python3 -m pytest tests/ -k "not autogen" -v  # 跳过 autogen(慢)

约定:
  - 每个测试文件对应一条链路(技能、agent 循环、LLM 客户端)
  - 不依赖 FastAPI 启动,直接 import 内部函数测
  - 涉及 LLM 调用的测都用 pytest.mark.slow 标记,可单独跳过
"""
import os
import sys
from pathlib import Path

# 把项目根加到 sys.path,这样 import app.xxx 直接能用
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))