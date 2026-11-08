"""图片预处理：HEIC 转换、EXIF 转正、压缩。原图只在内存中出现。"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:  # 镜像缺少 HEIC 支持时给出明确提示，而不是一句"无法读取"
    HEIF_SUPPORTED = False

MAX_UPLOAD = 20 * 1024 * 1024
MAX_SIDE = 1600
TARGET_BYTES = 1_000_000
HEIF_HINT = b"ftyp"


class ImageError(ValueError):
    pass


def _looks_like_heif(data: bytes) -> bool:
    return len(data) > 12 and data[4:8] == HEIF_HINT and data[8:12] in (
        b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis"
    )


def prepare(data: bytes, mime: str = "") -> tuple[bytes, dict]:
    """返回 (压缩后的 JPEG bytes, 图片信息)。"""
    if not data:
        raise ImageError("没有收到图片")
    if len(data) > MAX_UPLOAD:
        raise ImageError(f"图片超过 {MAX_UPLOAD // 1024 // 1024}MB，请先压缩后再上传")

    if _looks_like_heif(data) and not HEIF_SUPPORTED:
        raise ImageError("当前镜像未启用 HEIC 支持，请把照片另存为 JPEG 后上传")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        if _looks_like_heif(data):
            raise ImageError("HEIC 照片解码失败，请改用 JPEG 上传") from exc
        raise ImageError("无法读取这张图片，请换用 JPEG / PNG / WebP 格式") from exc

    original_size = img.size
    try:
        orientation = (img.getexif() or {}).get(274, 1)
    except Exception:
        orientation = 1
    fixed_orientation = orientation not in (1, 0, None)

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        img = canvas
    elif img.mode != "RGB":
        img = img.convert("RGB")

    scale = min(1.0, MAX_SIDE / max(img.size))
    if scale < 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)

    quality = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) <= TARGET_BYTES or quality <= 60:
            break
        quality -= 7

    if len(out) > TARGET_BYTES:
        factor = (TARGET_BYTES / len(out)) ** 0.5
        img = img.resize((max(320, round(img.width * factor)), max(320, round(img.height * factor))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72, optimize=True)
        out = buf.getvalue()

    info = {
        "original_width": original_size[0],
        "original_height": original_size[1],
        "width": img.width,
        "height": img.height,
        "original_bytes": len(data),
        "bytes": len(out),
        "exif_fixed": fixed_orientation,
    }
    return out, info


def tiny_test_image() -> bytes:
    """测试连接用的一张极小灰图，避免消耗真实点评额度。"""
    img = Image.new("RGB", (8, 8), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
