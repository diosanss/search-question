"""Background monitoring loop: capture -> OCR -> AI -> UI events."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from . import capture, llm
from .config import Config
from .ocr_engine import OcrError, OcrResult, OcrService, normalize_for_hash

log = logging.getLogger(__name__)


@dataclass
class UiBridge:
    """The UI passes in a synchronous function that runs code on the Tk thread."""

    call: Callable[[Callable[[], Any], float, Any], Any]

    def invoke(self, fn: Callable[[], Any], default=None, timeout: float = 3.0):
        try:
            return self.call(fn, timeout, default)
        except Exception:
            log.debug("UI call failed", exc_info=True)
            return default


class MonitorEngine:
    def __init__(self, cfg: Config, ui: UiBridge, events: queue.Queue):
        self.cfg = cfg
        self.ui = ui
        self.events = events
        self.ocr = OcrService()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._paused = True
        self._force = False
        self._cancel = threading.Event()
        self._state_lock = threading.Lock()
        self._app = None
        self.answer_count = 0
        self.skip_count = 0
        self._last_thumb = None
        self._last_text_hash: str | None = None
        self._last_region = None
        self._retry_after = 0.0
        self._last_error: str | None = None
        self._last_error_at = 0.0
        self.last_question = ""
        self.last_answer = ""
        self.last_capture_at: datetime | None = None

    # ---- public controls -------------------------------------------------------
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._paused)

    def attach_app(self, app) -> None:
        self._app = app

    def start(self) -> None:
        with self._state_lock:
            self._paused = False
            self._force = True
            self._reset_detection()
            if self._thread and self._thread.is_alive():
                self._wake.set()
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="screen-answer-monitor", daemon=True)
            self._thread.start()
        self._emit({"type": "status", "phase": "starting", "message": "正在准备读取…"})

    def pause(self) -> None:
        self._paused = True
        self._cancel.set()
        self._wake.set()
        self._emit({"type": "status", "phase": "paused", "message": "已暂停"})

    def resume(self) -> None:
        self._paused = False
        self._force = True
        self._reset_detection()
        self._wake.set()
        self._emit({"type": "status", "phase": "watching", "message": "正在监测屏幕"})

    def force_capture(self) -> None:
        self._force = True
        self._cancel.set()
        self._wake.set()

    def reset(self) -> None:
        """Call after settings changed so the same screen is evaluated again."""
        self._reset_detection()
        self._retry_after = 0.0
        self._force = True
        self._wake.set()

    def shutdown(self) -> None:
        self._stop.set()
        self._paused = True
        self._cancel.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None

    # ---- internals -------------------------------------------------------------
    def _reset_detection(self) -> None:
        self._last_thumb = None
        self._last_text_hash = None
        self._last_region = None

    def _emit(self, event: dict) -> None:
        try:
            self.events.put_nowait(event)
        except queue.Full:
            if event.get("type") in ("frame", "delta", "skip", "stats"):
                return
            try:
                self.events.get_nowait()
                self.events.put_nowait(event)
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._paused:
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            force = self._force
            self._force = False
            started = time.monotonic()
            try:
                self._tick(force)
            except Exception as exc:
                log.exception("Monitor tick failed")
                self._report_error(f"读取屏幕时出错：{exc}")
            if self._stop.is_set():
                break
            if self._paused:
                continue
            if self._force:
                continue
            elapsed = time.monotonic() - started
            wait = max(0.4, self.cfg.interval - elapsed)
            self._wake.wait(wait)
            self._wake.clear()

    def _tick(self, force: bool) -> None:
        region_cfg = self.cfg.region if self.cfg.capture.get("mode") == "region" else None
        use_region = bool(region_cfg)
        try:
            target = capture.clamp_region(region_cfg)
        except capture.CaptureError as exc:
            self._report_error(str(exc))
            return
        if self._last_region != target:
            self._reset_detection()
        self._last_region = target

        # 1. Cheap probe with our own windows masked out. No flicker on idle
        #    screens because nothing needs to be hidden for this step.
        own = self._own_rects()
        try:
            probe = capture.grab(target)
        except capture.CaptureError as exc:
            self._report_error(str(exc))
            return
        probe_for_diff = capture.mask_regions(probe, own, target, fill=(12, 12, 12)) if own else probe
        probe_thumb = capture.thumb(probe_for_diff)
        retry_due = self._retry_after > 0 and time.monotonic() >= self._retry_after
        if not force and not retry_due and self._last_thumb is not None:
            changed, metrics = capture.is_changed(
                self._last_thumb,
                probe_thumb,
                mean_threshold=float(self.cfg.capture.get("change_threshold", 2.0)),
            )
            log.debug(
                "Frame diff mean=%.3f hard=%.4f soft=%.4f changed=%s",
                metrics.mean,
                metrics.hard_ratio,
                metrics.soft_ratio,
                changed,
            )
            if not changed:
                self.skip_count += 1
                self._emit(
                    {
                        "type": "skip",
                        "reason": "unchanged",
                        "score": round(metrics.mean, 2),
                        "hard": round(metrics.hard_ratio, 4),
                        "soft": round(metrics.soft_ratio, 4),
                    }
                )
                self._emit_stats()
                return
        if not force and not retry_due and self._last_text_hash is not None and time.monotonic() < self._retry_after:
            self.skip_count += 1
            self._emit({"type": "skip", "reason": "backoff"})
            self._emit_stats()
            return

        # 2. A real change: hide our own windows for a clean frame, then restore.
        self._emit({"type": "status", "phase": "capturing", "message": "发现画面变化，正在读取…"})
        try:
            clean = self._capture_clean(target, own)
        except capture.CaptureError as exc:
            self._report_error(str(exc))
            return
        own_after = self._own_rects()
        self._last_thumb = capture.thumb(
            capture.mask_regions(clean, own_after, target, fill=(12, 12, 12)) if own_after else clean
        )
        if own_after:
            # Do not OCR the app's own overlay/main window.  Fill its area with
            # the page's median color instead of flashing the windows off.
            clean = capture.mask_regions(clean, own_after, target)
        self.last_capture_at = datetime.now()
        self._emit({"type": "frame", "image": clean, "region": target, "at": self.last_capture_at})
        self._emit_stats()

        # 3. OCR locally.
        self._emit({"type": "status", "phase": "ocr", "message": "正在识别文字…"})
        ocr_error: str | None = None
        try:
            result = self.ocr.recognize(clean)
        except OcrError as exc:
            ocr_error = str(exc)
            result = OcrResult("")
            log.warning("OCR error: %s", exc)
            if not self.cfg.api.get("vision") or self.cfg.ocr_only:
                self._report_error(ocr_error)
                return
            self._emit({"type": "warning", "message": "OCR 不可用，改用视觉模型直接看图"})

        question_text = (result.focus_text or result.text or "").strip()
        if use_region:
            # The user already selected exactly the question area; do not run
            # the automatic focus heuristic on top of it.
            question_text = (result.text or "").strip()
        if self.cfg.ocr_only and not question_text:
            self._report_error("没有识别到文字。请把题目区域放大，或改用框选。")
            return
        if not question_text and not self.cfg.api.get("vision"):
            self._report_error("没有识别到文字。请把题目区域放大一些，或改成框选题目区域后重试。")
            return
        self.last_question = question_text
        question_hash = normalize_for_hash(question_text)
        if not force and not retry_due and question_hash and question_hash == self._last_text_hash:
            self.skip_count += 1
            self._emit({"type": "skip", "reason": "same_text"})
            self._emit_stats()
            return
        self._emit(
            {
                "type": "ocr",
                "text": question_text,
                "chars": len(question_text),
                "focus": (not use_region) and result.focus_box is not None,
            }
        )

        if self.cfg.ocr_only:
            self._last_text_hash = question_hash or None
            self._retry_after = 0.0
            self._emit(
                {
                    "type": "ocr_text",
                    "text": question_text,
                    "chars": len(question_text),
                }
            )
            self._emit({"type": "status", "phase": "ocr_only", "message": "文字已复制，继续监测"})
            return

        if self.cfg.needs_key and not self.cfg.get_api_key():
            self._last_text_hash = question_hash or None
            self._emit({"type": "needs_setup", "text": question_text, "reason": "no_key"})
            self._emit({"type": "status", "phase": "needs_setup", "message": "还没有配置模型 API"})
            return

        # 4. Ask the model, optionally with a cropped screenshot.
        image = None
        if self.cfg.api.get("vision"):
            focus = result.focus_box
            if use_region:
                image = clean
            elif focus:
                x, y, w, h = focus
                try:
                    image = clean.crop((x, y, x + w, y + h))
                except Exception:
                    image = clean
            else:
                image = clean
        data_url = capture.data_url_jpeg(image) if image is not None else None
        self._emit({"type": "status", "phase": "thinking", "message": "正在向模型求解…"})
        self._emit({"type": "analyzing", "text": question_text, "has_image": data_url is not None})

        self._cancel = threading.Event()
        last_emit = 0.0
        started = time.monotonic()

        def on_delta(full_text: str):
            nonlocal last_emit
            now = time.monotonic()
            if now - last_emit >= 0.055:
                last_emit = now
                self._emit({"type": "delta", "text": full_text})

        try:
            result_llm = llm.stream_answer(
                self.cfg,
                question_text,
                data_url,
                self._cancel,
                on_delta,
            )
        except llm.LLMCancelled:
            self._emit({"type": "status", "phase": "paused" if self._paused else "watching", "message": "已取消"})
            return
        except llm.LLMError as exc:
            self._retry_after = time.monotonic() + 20.0
            self._last_text_hash = question_hash or None
            self._report_error(str(exc))
            return

        if self._cancel.is_set():
            return
        answer = result_llm.text.strip()
        self.last_answer = answer
        self.answer_count += 1
        self._retry_after = 0.0
        self._last_text_hash = question_hash or None
        elapsed = time.monotonic() - started
        self._emit(
            {
                "type": "done",
                "text": answer,
                "model": result_llm.model,
                "elapsed": round(elapsed, 1),
                "chars": len(question_text),
            }
        )
        self._emit({"type": "status", "phase": "watching", "message": "继续监测中"})
        self._emit_stats()

    def _own_rects(self) -> list:
        if self._app is None:
            return []
        return self.ui.invoke(self._app.own_window_rects, default=[], timeout=2.0) or []

    def _capture_clean(self, target, own: list) -> Any:
        # Never hide/animate the app windows: a screen flash is worse than
        # masking the small area occupied by the overlay.  The caller masks
        # own_after from the captured image before OCR.
        return capture.grab(target)

    def _report_error(self, message: str) -> None:
        now = time.monotonic()
        if message == self._last_error and now - self._last_error_at < 25:
            return
        self._last_error = message
        self._last_error_at = now
        log.warning("Monitor error: %s", message)
        self._emit({"type": "error", "message": message})
        self._emit({"type": "status", "phase": "error", "message": "出错了"})

    def _emit_stats(self) -> None:
        self._emit(
            {
                "type": "stats",
                "answers": self.answer_count,
                "skips": self.skip_count,
            }
        )
