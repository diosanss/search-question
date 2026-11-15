"""Screen grabbing and frame change detection."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import mss
from PIL import Image, ImageChops, ImageOps

log = logging.getLogger(__name__)

Region = tuple[int, int, int, int]  # left, top, width, height


class CaptureError(RuntimeError):
    pass


def full_region() -> Region:
    try:
        with mss.MSS() as sct:
            mon = sct.monitors[0]
            return (int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"]))
    except Exception as exc:
        raise CaptureError(f"无法读取屏幕尺寸：{exc}") from exc


def _clamp(region: Region) -> Region:
    vx, vy, vw, vh = full_region()
    x, y, w, h = region
    left = max(vx, int(x))
    top = max(vy, int(y))
    right = min(vx + vw, int(x + w))
    bottom = min(vy + vh, int(y + h))
    if right - left < 8 or bottom - top < 8:
        raise CaptureError("选区太小或不在屏幕范围内")
    return left, top, right - left, bottom - top


def clamp_region(region: Region | None) -> Region:
    return _clamp(region) if region else full_region()


def grab(region: Region | None = None, mask: list[Region] | None = None) -> Image.Image:
    target = clamp_region(region)
    try:
        with mss.MSS() as sct:
            shot = sct.grab(
                {
                    "left": target[0],
                    "top": target[1],
                    "width": target[2],
                    "height": target[3],
                }
            )
    except Exception as exc:
        raise CaptureError(f"截屏失败：{exc}") from exc
    try:
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception as exc:
        raise CaptureError(f"截图转换失败：{exc}") from exc
    if mask:
        image = mask_regions(image, mask, target)
    return image


def mask_regions(
    image: Image.Image,
    rects: list[Region],
    origin: Region,
    fill: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Black out our own windows when building a change-detection frame.

    With ``fill=None`` the mask uses the image's median color, which keeps an
    OCR page looking like a page instead of a black rectangle.
    """
    if not rects:
        return image
    out = image.copy()
    ox, oy, ow, oh = origin
    from PIL import ImageDraw, ImageStat

    draw = ImageDraw.Draw(out)
    if fill is None:
        try:
            med = ImageStat.Stat(out.resize((32, 32))).median
            fill = tuple(int(v) for v in med[:3])
        except Exception:
            fill = (255, 255, 255)
    for x, y, w, h in rects:
        x1 = max(0, x - ox)
        y1 = max(0, y - oy)
        x2 = min(ow, x - ox + w)
        y2 = min(oh, y - oy + h)
        if x2 > x1 and y2 > y1:
            draw.rectangle((x1, y1, x2, y2), fill=fill)
    return out


def thumb(image: Image.Image, size: tuple[int, int] = (256, 160)) -> Image.Image:
    return ImageOps.grayscale(image).resize(size, Image.Resampling.BOX)


@dataclass
class DiffMetrics:
    mean: float
    hard_ratio: float  # fraction of pixels with a strong difference
    soft_ratio: float  # fraction of pixels with any meaningful difference

    @property
    def score(self) -> float:
        return self.mean


def diff_metrics(a: Image.Image, b: Image.Image) -> DiffMetrics:
    """Measure both average and *localized* differences.

    The average pixel difference over a whole 2560x1600 screen is tiny when
    only a question block changes (usually < 1.0), so a mean-only threshold
    misses the next question.  Counting the changed pixels fixes that while a
    blinking cursor still stays below the threshold.
    """
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.BILINEAR)
    try:
        diff = ImageChops.difference(a, b)
        hist = diff.histogram()
        total = max(1, a.width * a.height)
        mean = sum(i * count for i, count in enumerate(hist)) / total
        hard_ratio = sum(hist[20:]) / total
        soft_ratio = sum(hist[8:]) / total
        return DiffMetrics(mean, hard_ratio, soft_ratio)
    except Exception:
        return DiffMetrics(999.0, 1.0, 1.0)


def diff_score(a: Image.Image, b: Image.Image) -> float:
    return diff_metrics(a, b).mean


def is_changed(
    a: Image.Image,
    b: Image.Image,
    mean_threshold: float = 2.0,
    hard_ratio_threshold: float = 0.0010,
    soft_ratio_threshold: float = 0.0030,
) -> tuple[bool, DiffMetrics]:
    metrics = diff_metrics(a, b)
    changed = (
        metrics.mean >= mean_threshold
        or metrics.hard_ratio >= hard_ratio_threshold
        or metrics.soft_ratio >= soft_ratio_threshold
    )
    return changed, metrics


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False, compress_level=3)
    return buf.getvalue()


def data_url_jpeg(image: Image.Image, max_edge: int = 1800, quality: int = 84) -> str:
    """Small JPEG suitable for vision APIs."""
    import base64

    im = image.convert("RGB")
    if max(im.size) > max_edge:
        im = im.copy()
        im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def intersects(a: Region, b: Region) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


@dataclass
class Frame:
    image: Image.Image
    region: Region
    timestamp: float

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def masked_thumb(self, rects: list[Region]) -> Image.Image:
        return thumb(mask_regions(self.image, rects, self.region))
