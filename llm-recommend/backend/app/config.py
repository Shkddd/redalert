"""配置"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.hermes/.env"))

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "recommend.db"

# LLM (OpenAI 兼容)
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or os.getenv("XIAOMI_BASE_URL")
    or os.getenv("MINIMAX_CN_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
).rstrip("/")
LLM_API_KEY = ""
for var in ("LLM_API_KEY", "XIAOMI_API_KEY", "MINIMAX_CN_API_KEY", "OPENAI_API_KEY"):
    v = os.getenv(var)
    if v:
        LLM_API_KEY = v
        break
LLM_MODEL = os.getenv("LLM_MODEL", "mimo-v2.5")

# Embedding (复用 local-rag 的 BGE)
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
EMBED_DIM = 512

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8002"))
