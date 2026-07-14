"""ContractReview configuration — loads .env with sensible defaults."""

import os
import re
from pathlib import Path
from functools import lru_cache

# Load .env from project root manually
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("\"'")
            if key and not os.environ.get(key):
                os.environ[key] = val


@lru_cache()
def get_settings():
    return Settings()


class Settings:
    # LLM
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")

    # Paths
    project_root: Path = Path(__file__).parent.parent.parent
    upload_dir: Path = project_root / "backend" / "data" / "uploads"
    db_path: Path = project_root / "backend" / "data" / "contract_review.db"

    # Server
    host: str = "0.0.0.0"
    port: int = int(os.getenv("PORT", "8001"))
