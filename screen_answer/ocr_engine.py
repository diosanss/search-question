"""Local OCR through the Windows.Media.Ocr engine (no cloud, no extra model)."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field

from PIL import Image

from . import capture

log = logging.getLogger(__name__)


class OcrError(RuntimeError):
    pass


_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_PUNCT = r"，。、；：！？（）【】《》“”‘’·…—～"
_SPACE_AROUND_CJK = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])")
_SPACE_BEFORE_PUNCT = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK_PUNCT}])")
_SPACE_AFTER_PUNCT = re.compile(rf"(?<=[{_CJK_PUNCT}])[ \t]+(?=[{_CJK}])")
_SPACE_DIGIT_UNIT = re.compile(rf"(?<=[0-9])[ \t]+(?=[{_CJK}%％])")
_SPACE_UNIT_DIGIT = re.compile(rf"(?<=[{_CJK}%％])[ \t]+(?=[0-9])")

_QUESTION_RE = re.compile(
    r"^(?:第?\s*\d+\s*[题.、．)]|[（(]?\s*[一二三四五六七八九十]+\s*[)）、.]|"
    r"单选|多选|判断|填空|简答|问答|材料|阅读|选择题|判断题|单选题|多选题|不定项)"
)
_OPTION_RE = re.compile(r"^[A-HＡ-Ｈ]\s*[.、．)）:：]\s*\S")
_ANSWER_HINT_RE = re.compile(r"[（(]\s*[)）]|_{3,}|＿{2,}")


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = (
        text.replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    text = _SPACE_AROUND_CJK.sub("", text)
    text = _SPACE_BEFORE_PUNCT.sub("", text)
    text = _SPACE_AFTER_PUNCT.sub("", text)
    text = _SPACE_DIGIT_UNIT.sub("", text)
    text = _SPACE_UNIT_DIGIT.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip(" \t")
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        # Lines made only of punctuation are OCR noise.
        if len(line) == 1 and line in "|·•_-—~`'\"<>《》":
            continue
        # OCR sometimes turns a radio button / separator into a short line
        # like "/ 皿丨司". Keep real text, drop short lines that start with a
        # symbol and contain no Latin letters or digits.
        if (
            len(line) <= 12
            and re.match(r"^[\s|/\\·•~_\-—=<>]+", line)
            and not re.search(r"[A-Za-z0-9]", line)
        ):
            continue
        if lines and line == lines[-1]:
            continue
        lines.append(line)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines).strip()


def normalize_for_hash(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


@dataclass
class OcrLine:
    x: int
    y: int
    w: int
    h: int
    text: str

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass
class OcrResult:
    text: str
    lines: list[OcrLine] = field(default_factory=list)
    focus_box: tuple[int, int, int, int] | None = None
    focus_text: str = ""

    def __bool__(self) -> bool:
        return bool(self.text.strip())


def _find_focus(lines: list[OcrLine], size: tuple[int, int]) -> tuple[tuple[int, int, int, int] | None, str]:
    """Find the question block so we can crop away browser chrome/desktop icons."""
    if not lines:
        return None, ""
    question_idx: list[int] = []
    option_idx: list[int] = []
    for i, line in enumerate(lines):
        text = line.text.strip()
        if len(text) < 2:
            continue
        if _OPTION_RE.match(text):
            option_idx.append(i)
        elif _QUESTION_RE.match(text):
            question_idx.append(i)

    chosen: list[int] = []
    if question_idx:
        chosen.extend(question_idx)
        chosen.extend(option_idx)
        # A single question header with no options still deserves a crop if it
        # looks like a fill-in-the-blank question.
        if not option_idx:
            for i, line in enumerate(lines):
                if _ANSWER_HINT_RE.search(line.text) and abs(line.y - lines[question_idx[0]].y) < 220:
                    chosen.append(i)
    if not chosen:
        return None, ""

    core = [lines[i] for i in chosen]
    top = min(l.y for l in core)
    bottom = max(l.bottom for l in core)
    left = min(l.x for l in core)
    right = max(l.right for l in core)

    # OCR often misses the small A/B/C/D radio letters. In that case the
    # option text does not match _OPTION_RE, so look further down the page
    # instead of cropping the options away.
    if len(option_idx) < 2:
        bottom = min(size[1], bottom + 640)
    else:
        bottom = min(size[1], bottom + 80)

    # Include adjacent lines in the same vertical/horizontal band (question
    # stem wrapped across lines, option explanations, etc.).
    band = [
        l
        for l in lines
        if l.bottom >= top - 24 and l.y <= bottom and l.right >= left - 70 and l.x <= right + 120
    ]
    if band:
        top = min(l.y for l in band)
        bottom = max(l.bottom for l in band)
        left = min(l.x for l in band)
        right = max(l.right for l in band)
    pad_x, pad_top, pad_bottom = 70, 55, 60
    left = max(0, left - pad_x)
    top = max(0, top - pad_top)
    right = min(size[0], right + pad_x)
    bottom = min(size[1], bottom + pad_bottom)
    if right - left < 320:
        extra = (320 - (right - left)) // 2
        left = max(0, left - extra)
        right = min(size[0], right + extra)
    if bottom - top < 180:
        bottom = min(size[1], top + 180)
    box = (left, top, right - left, bottom - top)
    if box[2] * box[3] > size[0] * size[1] * 0.92:
        return None, ""
    focus_text = clean_text(
        "\n".join(
            l.text
            for l in band
            if l.bottom >= top and l.y <= bottom and l.right >= left and l.x <= right
        )
    )
    return box, focus_text


class OcrService:
    def __init__(self, language: str = "zh-Hans-CN"):
        self.language = language
        self._engine = None
        self._lock = threading.Lock()
        self._init_error: str | None = None

    def _create_engine(self):
        from winrt.windows.media.ocr import OcrEngine

        available = list(OcrEngine.available_recognizer_languages)
        tags = [str(lang.language_tag) for lang in available]
        log.info("Windows OCR languages: %s", ", ".join(tags) or "none")
        if not available:
            raise OcrError("Windows 没有安装可用的 OCR 语言包")
        chosen = None
        for lang in available:
            if str(lang.language_tag).lower() == self.language.lower():
                chosen = lang
                break
        if chosen is None:
            for lang in available:
                if str(lang.language_tag).lower().startswith("zh"):
                    chosen = lang
                    break
        if chosen is None:
            chosen = available[0]
        engine = OcrEngine.try_create_from_language(chosen)
        if engine is None:
            raise OcrError("无法创建 Windows OCR 引擎，请先在 Windows 设置中安装中文 OCR 语言包")
        log.info("Using OCR language: %s", chosen.language_tag)
        return engine

    def _engine_or_raise(self):
        with self._lock:
            if self._engine is None:
                try:
                    self._engine = self._create_engine()
                except Exception as exc:
                    self._init_error = str(exc)
                    raise
            return self._engine

    @staticmethod
    def _prepare(image: Image.Image) -> tuple[Image.Image, float]:
        im = image.convert("RGB")
        w, h = im.size
        longest = max(w, h)
        factor = 1.0
        # Tiny region screenshots benefit from upscaling; full screens don't.
        if longest < 1300:
            factor = min(2.2, 1500.0 / max(1, longest))
            if factor > 1.15:
                im = im.resize((int(w * factor), int(h * factor)), Image.Resampling.LANCZOS)
            else:
                factor = 1.0
        elif longest > 4200:
            factor = 4200.0 / longest
            im = im.resize((int(w * factor), int(h * factor)), Image.Resampling.LANCZOS)
        return im, factor

    async def _recognize_async(self, png: bytes, engine) -> list[OcrLine]:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        try:
            writer.write_bytes(png)
            await writer.store_async()
            await writer.flush_async()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            result = await engine.recognize_async(bitmap)
            items: list[OcrLine] = []
            for line in result.lines:
                text = (line.text or "").strip()
                if not text:
                    continue
                xs: list[float] = []
                ys: list[float] = []
                rights: list[float] = []
                bottoms: list[float] = []
                for word in line.words:
                    rect = word.bounding_rect
                    xs.append(float(rect.x))
                    ys.append(float(rect.y))
                    rights.append(float(rect.x + rect.width))
                    bottoms.append(float(rect.y + rect.height))
                x = int(min(xs)) if xs else 0
                y = int(min(ys)) if ys else 0
                r = int(max(rights)) if rights else x
                b = int(max(bottoms)) if bottoms else y
                items.append(OcrLine(x, y, max(1, r - x), max(1, b - y), text))
            # Read top-to-bottom, then left-to-right for lines on the same row.
            items.sort(key=lambda item: (round(item.y / 16.0), item.x, item.y))
            return items
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def recognize(self, image: Image.Image) -> OcrResult:
        if image.width < 3 or image.height < 3:
            return OcrResult("")
        engine = self._engine_or_raise()
        prepared, factor = self._prepare(image)
        png = capture.png_bytes(prepared)
        try:
            lines = asyncio.run(self._recognize_async(png, engine))
        except OcrError:
            raise
        except Exception as exc:
            log.exception("OCR failed")
            raise OcrError(f"OCR 识别失败：{exc}") from exc
        if factor != 1.0:
            inv = 1.0 / factor
            lines = [
                OcrLine(
                    int(l.x * inv),
                    int(l.y * inv),
                    max(1, int(l.w * inv)),
                    max(1, int(l.h * inv)),
                    l.text,
                )
                for l in lines
            ]
        text = clean_text("\n".join(l.text for l in lines))
        focus_box, focus_text = _find_focus(lines, image.size)
        return OcrResult(text, lines, focus_box, focus_text)

    def recognize_bytes(self, png: bytes) -> OcrResult:
        with Image.open(io.BytesIO(png)) as im:
            return self.recognize(im)
