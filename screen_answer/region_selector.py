"""Full-screen drag-to-select region overlay."""

from __future__ import annotations

import ctypes
import logging
import tkinter as tk
from typing import Callable

from . import theme, winutil
from .theme import Metrics

log = logging.getLogger(__name__)


def virtual_screen() -> tuple[int, int, int, int]:
    try:
        user32 = ctypes.windll.user32
        return (
            int(user32.GetSystemMetrics(76)),
            int(user32.GetSystemMetrics(77)),
            int(user32.GetSystemMetrics(78)),
            int(user32.GetSystemMetrics(79)),
        )
    except Exception:
        return (0, 0, 1280, 800)


class RegionSelector:
    def __init__(
        self,
        root: tk.Tk,
        metrics: Metrics,
        on_done: Callable[[tuple[int, int, int, int] | None], None],
        title_text: str = "拖动框选题目区域    ·    Esc 取消",
        hint_text: str = "提示：框住题干和选项即可；之后只读取这个区域，识别更准",
    ):
        self.root = root
        self.m = metrics
        self.on_done = on_done
        self.title_text = title_text
        self.hint_text = hint_text
        self.vx, self.vy, self.vw, self.vh = virtual_screen()
        self.start = None
        self.rect_id = None
        self.size_bg = None
        self.size_text = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.58)
        except Exception:
            pass
        self.win.configure(bg="#000000")
        self.win.geometry(f"{self.vw}x{self.vh}{self.vx:+d}{self.vy:+d}")
        self.canvas = tk.Canvas(
            self.win,
            bg="#000000",
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        w = self.m.px(600)
        h = self.m.px(52)
        cx = self.vw // 2
        self.canvas.create_rectangle(
            cx - w // 2, self.m.px(34), cx + w // 2, self.m.px(34) + h,
            fill=theme.PANEL, outline=theme.BORDER, width=1,
        )
        self.canvas.create_text(
            cx, self.m.px(34) + h // 2,
            text=self.title_text,
            fill=theme.TEXT,
            font=self.m.font(10.5, "bold"),
        )
        self.hint = self.canvas.create_text(
            cx,
            self.vh - self.m.px(82),
            text=self.hint_text,
            fill=theme.MUTED,
            font=self.m.font(9),
        )

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.win.bind("<Escape>", lambda _e: self._cancel())
        self.win.bind("<ButtonPress-3>", lambda _e: self._cancel())
        self.win.after(50, self._focus)
        self.win.focus_force()
        try:
            self.win.grab_set()
        except Exception:
            pass

    def _focus(self):
        try:
            self.win.lift()
            self.win.attributes("-topmost", True)
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            winutil.bring_topmost(int(hwnd), activate=True)
            self.win.focus_force()
            self.canvas.focus_set()
        except Exception:
            pass

    def _press(self, event):
        self.start = (event.x, event.y)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self._clear_size()

    def _move(self, event):
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = event.x, event.y
        left, top = min(x0, x1), min(y0, y1)
        right, bottom = max(x0, x1), max(y0, y1)
        if self.rect_id:
            self.canvas.coords(self.rect_id, left, top, right, bottom)
        else:
            self.rect_id = self.canvas.create_rectangle(
                left, top, right, bottom,
                outline=theme.ACCENT, width=max(2, self.m.px(2)),
            )
        self._show_size(right - left, bottom - top, event.x + self.m.px(16), event.y + self.m.px(18))

    def _show_size(self, w: int, h: int, x: int, y: int):
        text = f"{w} × {h}"
        tw = self.m.px(112)
        th = self.m.px(28)
        x = max(self.m.px(8), min(self.vw - tw - self.m.px(8), x))
        y = max(self.m.px(8), min(self.vh - th - self.m.px(8), y))
        if self.size_bg is None:
            self.size_bg = self.canvas.create_rectangle(
                x, y, x + tw, y + th, fill=theme.PANEL, outline=theme.BORDER
            )
            self.size_text = self.canvas.create_text(
                x + tw // 2, y + th // 2, text=text, fill=theme.TEXT, font=self.m.font(9, "bold")
            )
        else:
            self.canvas.coords(self.size_bg, x, y, x + tw, y + th)
            self.canvas.coords(self.size_text, x + tw // 2, y + th // 2)
            self.canvas.itemconfigure(self.size_text, text=text)

    def _clear_size(self):
        for item in (self.size_bg, self.size_text):
            if item:
                self.canvas.delete(item)
        self.size_bg = self.size_text = None

    def _release(self, event):
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = event.x, event.y
        left, top = min(x0, x1), min(y0, y1)
        right, bottom = max(x0, x1), max(y0, y1)
        if right - left < self.m.px(40) or bottom - top < self.m.px(30):
            self._cancel()
            return
        region = (
            int(self.vx + left),
            int(self.vy + top),
            int(right - left),
            int(bottom - top),
        )
        self._close(region)

    def _cancel(self):
        self._close(None)

    def _close(self, region):
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
        try:
            self.on_done(region)
        except Exception:
            log.exception("Region callback failed")
