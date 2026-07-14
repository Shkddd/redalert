"""ChatBI configuration — loads from .env with sensible defaults."""

import os
import re
from pathlib import Path
from functools import lru_cache

# Load .env from project root manually (avoid dotenv dependency)
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


class Settings:
    # LLM provider (OpenAI-compatible API)
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/chatbi.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["*"]

    # Data
    seed_data_size: int = 500

    def __init__(self):
        self.llm_base_url = os.getenv("LLM_BASE_URL", self.llm_base_url)
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", self.llm_model)
        db_path = os.getenv("DATABASE_URL", "")
        if db_path:
            self.database_url = db_path
        self.host = os.getenv("HOST", self.host)
        port_str = os.getenv("PORT", "")
        if port_str:
            self.port = int(port_str)
        seed_str = os.getenv("SEED_DATA_SIZE", "")
        if seed_str:
            self.seed_data_size = int(seed_str)

    @property
    def db_path(self) -> str:
        """Extract the filesystem path from sqlite URL."""
        raw = self.database_url.replace("sqlite+aiosqlite:///", "")
        raw = raw.replace("sqlite:///", "")
        return raw

    @property
    def data_dir(self) -> Path:
        db = Path(self.db_path)
        return db.parent.resolve()


@lru_cache()
def get_settings() -> Settings:
    return Settings()
