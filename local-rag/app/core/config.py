"""项目配置"""
import os
from pathlib import Path

# 加载统一 key 仓库 ~/.hermes/.env(Hermes 项目的 secret 单点存放)
# 不存在则跳过,纯靠 os.environ(适合 CI/Docker)
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.hermes/.env"))

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # app/core/config.py → 项目根

# 数据目录
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
VERSION_DIR = DATA_DIR / "versions"
SQLITE_PATH = DATA_DIR / "rag.db"
MILVUS_PATH = DATA_DIR / "rag_milvus.db"

# 对象存储(模拟 OceanBase,本地目录 + HTTP 路由)
OBJECT_STORE_DIR = DATA_DIR / "object_store"
OBJECT_STORE_URL_PREFIX = "/files"  # FastAPI mount 路径

# Embedding 模型
EMB_MODEL = "BAAI/bge-small-zh-v1.5"
EMB_DIM = 512  # bge-small-zh 输出维度

# 切分参数
CHUNK_SIZE = 500        # 目标 chunk 字符数
CHUNK_OVERLAP = 80      # overlap

# BM25 参数
BM25_TOPK = 20

# 业务分类（演示用，预定义几类，LLM 兜底打"通用"）
BUSINESS_CATEGORIES = [
    "财务", "人事", "法务", "技术", "运营", "市场", "产品", "通用"
]

# JWT
JWT_SECRET = os.environ.get("RAG_JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
JWT_TTL_HOURS = 24

# 默认 admin 账号（首次启动自动建）
DEFAULT_ADMIN = {"username": "admin", "password": "***", "role": "admin"}

# 视觉模型(走 minimax-cn OpenAI 兼容 API;失败则降级)
VISION_ENABLED = os.getenv("VISION_ENABLED", "True").lower() not in ("false", "0", "")
# minimax-cn /v1/models 当前只列文本模型;实测 MiniMax-M3 支持图片理解(image_url)
VISION_MODEL = os.getenv("VISION_MODEL", "mimo-v2.5")
VISION_TIMEOUT_S = 60  # 视觉理解比纯文本慢(M3 含 thinking)
VISION_PROMPT = (
    "请用中文简洁描述这张图片。输出格式:一段话,2-4 句话,不要分点。"
    "重点说明: 1)图的主题/类型 2)关键数据/事实 3)如果是表格概括行列含义,"
    "如果是流程图说明步骤,如果是截图描述界面元素。"
)

# LLM 总结(查询最终答案生成)
LLM_MODEL_DEFAULT = os.getenv("MINIMAX_CN_MODEL", "MiniMax-M3")
LLM_TIMEOUT_S = 30
SUMMARY_PROMPT = ""  # 预留,目前用 synthesizer 内的 SYSTEM_PROMPT

# 通用 LLM / Vision API 配置
# 优先 xiaomi(mimo), 回退 minimax-cn, 最后兜底
LLM_BASE_URL_DEFAULT = (
    os.getenv("LLM_BASE_URL")
    or os.getenv("XIAOMI_BASE_URL")
    or os.getenv("MINIMAX_CN_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
).replace("/anthropic", "/v1")
# 多个 env 名都接受;按优先级查找
LLM_API_KEY_ENV_VARS = (
    "LLM_API_KEY",
    "XIAOMI_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENAI_API_KEY",
)

for d in [DATA_DIR, UPLOAD_DIR, VERSION_DIR, OBJECT_STORE_DIR]:
    d.mkdir(parents=True, exist_ok=True)