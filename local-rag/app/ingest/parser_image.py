"""
单图文件解析(jpg/png/...) - 整图作为一个 Page
- text 字段留给视觉 API 生成说明后填入(pipeline 阶段)
- section_path = 文件名去后缀
"""
import mimetypes
from pathlib import Path
from typing import List
from PIL import Image
import io

from app.ingest.parser_pdf import Page, ExtractedImage


def parse_image(path: Path) -> List[Page]:
    path = Path(path)
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"

    # Pillow 读 → 转 PNG(规范化)+ 拿尺寸
    try:
        img = Image.open(str(path))
        width, height = img.size
        # 统一转 PNG bytes(规范化)
        buf = io.BytesIO()
        # 转 RGB 避免 RGBA/P mode 的 PNG 兼容问题
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")
        img.save(buf, format="PNG")
        data = buf.getvalue()
        out_mime = "image/png"
    except Exception:
        # Pillow 读不了就退回到原始 bytes
        data = path.read_bytes()
        width = height = 0
        out_mime = mime

    ext_img = ExtractedImage(
        image_id="",  # pipeline 阶段填
        page_no=1,
        bytes=data,
        mime=out_mime,
        width=width,
        height=height,
    )
    page = Page(
        page_no=1,
        text="",  # 由视觉 API 后填
        images=[ext_img],
        section_path=path.stem,
        raw_meta={"source_format": mime, "original_path": str(path)},
    )
    return [page]


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    pages = parse_image(p)
    print(f"parsed {len(pages)} page, {len(pages[0].images)} images")
    print(f"image: {pages[0].images[0].width}x{pages[0].images[0].height} mime={pages[0].images[0].mime}")
