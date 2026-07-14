"""配置"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.hermes/.env"))

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# LLM(minimax-cn,OpenAI 兼容协议)
LLM_BASE_URL = os.environ.get("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com/v1").replace("/anthropic", "/v1")
LLM_API_KEY = os.environ.get("MINIMAX_CN_API_KEY", "")
LLM_MODEL = os.environ.get("MINIMAX_CN_MODEL", "MiniMax-M3")

# Agent
MAX_ITERATIONS = 15   # 单次任务最大循环次数
MAX_TOKENS = 4096
TEMPERATURE = 0.3

# RAG 复用(同机跑的话)
RAG_BASE_URL = os.environ.get("RAG_BASE_URL", "http://localhost:8000")

DATA_DIR.mkdir(parents=True, exist_ok=True)