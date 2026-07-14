"""
模拟 OceanBase 对象存储
- 把图片/文件落本地目录
- 返回 HTTP URL(/files/yyyy-mm-dd/uuid.ext)
- 与真实对象存储接口形状兼容(s3 / obs / oss 都能复用这个 wrapper)

真实部署时把 save_bytes 换成 boto3 / oss2 即可,调用方不变。
"""
import mimetypes
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Tuple

from app.core.config import OBJECT_STORE_DIR, OBJECT_STORE_URL_PREFIX


_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/gif": "gif",
}


def _ext_for(mime: str, fallback: str = "bin") -> str:
    if mime in _EXT_BY_MIME:
        return _EXT_BY_MIME[mime]
    # 用 mimetypes 兜底
    ext = mimetypes.guess_extension(mime or "")
    if ext:
        return ext.lstrip(".")
    return fallback


def save_bytes(data: bytes, mime: str = "image/png",
               doc_id: int = None) -> Tuple[str, str, Path]:
    """存字节流到对象存储,返回 (image_id, url, abs_path)"""
    if not data:
        raise ValueError("empty data")
    image_id = uuid.uuid4().hex
    ext = _ext_for(mime)
    day = datetime.now().strftime("%Y-%m-%d")
    sub = OBJECT_STORE_DIR / day
    sub.mkdir(parents=True, exist_ok=True)
    fname = f"{image_id}.{ext}"
    abs_path = sub / fname
    with open(abs_path, "wb") as f:
        f.write(data)
    rel = f"{day}/{fname}"
    url = f"{OBJECT_STORE_URL_PREFIX}/{rel}"
    return image_id, url, abs_path


def save_file(path: Path, mime: str = None) -> Tuple[str, str, Path]:
    """从本地文件存,自动识别 mime"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if mime is None:
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"
    with open(path, "rb") as f:
        return save_bytes(f.read(), mime=mime)


def get_path(url_or_id: str) -> Path:
    """url(/files/yyyy-mm-dd/uuid.ext) 或 image_id → 本地绝对路径"""
    if url_or_id.startswith(OBJECT_STORE_URL_PREFIX + "/"):
        rel = url_or_id[len(OBJECT_STORE_URL_PREFIX) + 1:]
        return OBJECT_STORE_DIR / rel
    # 当作 image_id 拼上今天日期试一下,失败再扫
    return OBJECT_STORE_DIR / url_or_id


if __name__ == "__main__":
    # 简单自测
    import os
    test_bytes = b"\x89PNG\r\n\x1a\n" + os.urandom(100)
    iid, url, p = save_bytes(test_bytes, "image/png")
    print("id:", iid)
    print("url:", url)
    print("path:", p)
    print("exists:", p.exists())
    p.unlink()
    print("---cleanup ok---")
