from __future__ import annotations

import base64
import io

from PIL import Image

MAX_DIMENSION = 1568
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_IMAGES_PER_REQUEST = 5
JPEG_QUALITY = 85
SUPPORTED_FORMATS = {"image/jpeg", "image/png", "image/webp"}


class ImagePreprocessError(Exception):
    pass


def validate_and_preprocess(images: list[dict]) -> list[dict]:
    if len(images) > MAX_IMAGES_PER_REQUEST:
        raise ImagePreprocessError(f"单次最多 {MAX_IMAGES_PER_REQUEST} 张图片，当前 {len(images)} 张。请分批上传。")

    processed: list[dict] = []
    for index, img in enumerate(images):
        media_type = img.get("media_type", "")
        if media_type not in SUPPORTED_FORMATS:
            raise ImagePreprocessError(f"第 {index + 1} 张图片格式不支持: {media_type}。支持 JPEG/PNG/WebP。")

        raw_b64 = img.get("data", "")
        if not raw_b64:
            raise ImagePreprocessError(f"第 {index + 1} 张图片缺少 data 字段。")

        try:
            raw_bytes = base64.b64decode(raw_b64)
        except Exception as exc:
            raise ImagePreprocessError(f"第 {index + 1} 张图片 base64 无法解析。") from exc

        if len(raw_bytes) > MAX_FILE_SIZE:
            raise ImagePreprocessError(f"第 {index + 1} 张图片超过 8MB 限制。")

        pil_img = Image.open(io.BytesIO(raw_bytes))
        width, height = pil_img.size
        long_edge = max(width, height)
        if long_edge > MAX_DIMENSION:
            scale = MAX_DIMENSION / long_edge
            pil_img = pil_img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")

        output = io.BytesIO()
        pil_img.save(output, format="JPEG", quality=JPEG_QUALITY)
        processed.append(
            {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(output.getvalue()).decode("utf-8"),
            }
        )

    return processed
