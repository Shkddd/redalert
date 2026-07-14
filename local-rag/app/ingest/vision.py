"""
视觉 API 客户端 - 给图片生成中文说明
走 minimax-cn OpenAI 兼容 /v1/chat/completions
失败/未配置时返回 None,调用方降级
"""
import base64
import os
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import (
    VISION_ENABLED,
    VISION_MODEL,
    VISION_TIMEOUT_S,
    VISION_PROMPT,
    LLM_BASE_URL_DEFAULT,
    LLM_API_KEY_ENV_VARS,
)


def _get_api_config() -> tuple:
    """从环境变量读 LLM 配置;config.py 已自动加载 .env,这里只查 env"""
    base_url = os.getenv("LLM_BASE_URL") or LLM_BASE_URL_DEFAULT
    base_url = base_url.rstrip("/")
    # 按优先级查多个 env var 名 (兼容不同项目的命名习惯)
    api_key = ""
    for env_name in LLM_API_KEY_ENV_VARS:
        v = os.getenv(env_name)
        if v:
            api_key = v
            break
    # 不打印 api_key 本身(避免敏感数据落日志)
    return base_url, api_key


def _to_data_uri(image_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def describe_image(image_bytes: bytes, mime: str = "image/png",
                   prompt: Optional[str] = None) -> Optional[str]:
    """
    调用视觉模型,返回中文图片说明。
    失败(超时/4xx/未配置) → 返回 None
    """
    if not VISION_ENABLED:
        return None
    if not image_bytes:
        return None

    base_url, api_key = _get_api_config()
    if not api_key:
        return None

    prompt = prompt or VISION_PROMPT
    data_uri = _to_data_uri(image_bytes, mime)

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "max_tokens": 300,
        "temperature": 0.2,
    }

    try:
        with httpx.Client(timeout=VISION_TIMEOUT_S) as client:
            r = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if r.status_code != 200:
                print(f"[vision] HTTP {r.status_code}: {r.text[:300]}")
                return None
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, str):
                return content.strip()
            # 防御: 视觉模型有时返回 list[dict] 形式
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        return c.get("text", "").strip()
            return None
    except Exception as e:
        print(f"[vision] exception: {type(e).__name__}: {e}")
        return None


def fallback_caption(width: int, height: int, page_no: int,
                     filename: str = "", mime: str = "") -> str:
    """降级说明(API 不可用时) - 用文件名+元信息生成可检索的描述"""
    parts = []
    # 文件名(去后缀)是最有价值的上下文
    if filename:
        name = Path(filename).stem if "." in filename else filename
        # 文件名通常包含业务含义,如"账单3""合同扫描件"
        parts.append(name)
    # 格式
    fmt_map = {
        "image/png": "PNG图片", "image/jpeg": "JPEG图片",
        "image/bmp": "BMP图片", "image/webp": "WebP图片",
        "image/gif": "GIF图片",
    }
    if mime:
        parts.append(fmt_map.get(mime, "图片"))
    else:
        parts.append("图片")
    # 尺寸(有意义时)
    if width > 0 and height > 0:
        parts.append(f"{width}x{height}")
    return " ".join(parts)


if __name__ == "__main__":
    # 自测: 生成一个简单 PNG 看调用是否能返回 None / 内容
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m app.ingest.vision <image_path>")
        sys.exit(0)
    p = sys.argv[1]
    with open(p, "rb") as f:
        data = f.read()
    import mimetypes
    mime, _ = mimetypes.guess_type(p)
    mime = mime or "image/png"
    print(f"[probe] api_key_set={bool(_get_api_config()[1])} base_url={_get_api_config()[0]}")
    cap = describe_image(data, mime)
    print("caption:", cap if cap else "(None - fallback)")
