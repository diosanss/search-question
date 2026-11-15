"""Main window and application wiring."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox
from typing import Any, Callable

from PIL import Image, ImageOps, ImageTk

from . import config as config_mod, theme, winutil
from .config import APP_NAME, Config
from .monitor import MonitorEngine, UiBridge
from .overlay import AnswerOverlay
from .region_selector import RegionSelector
from .settings_dialog import SettingsDialog
from .theme import Metrics, rounded_rect
from .widgets import Card, Dot, HoverButton, LinkLabel, Segmented, Toast

log = logging.getLogger(__name__)


def _top_hwnd(hwnd: int) -> int:
    try:
        user32 = ctypes.windll.user32
        current = hwnd
        parent = user32.GetParent(current)
        for _ in range(12):
            if not parent:
                break
            current = parent
            parent = user32.GetParent(current)
        return current
    except Exception:
        return hwnd


class ScreenAnswerApp:
    def __init__(self, root: tk.Tk, cfg: Config):
        self.root = root
        self.cfg = cfg
        self._closing = False
        self.m = Metrics(root)
        theme.configure_root(root, self.m)
        self._ui_queue: queue.Queue = queue.Queue(maxsize=100)
        self._hotkey_queue: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue(maxsize=120)
        self._preview_photo = None
        self.settings_dialog: SettingsDialog | None = None
        self.region_selector: RegionSelector | None = None
        self._overlay_was_visible = False
        self._hotkey_manager: winutil.HotkeyManager | None = None
        self._last_phase = "idle"
        self._last_mode = self.cfg.capture.get("mode", "full")
        self._last_read_text = "等待第一次读取"
        self._ocr_copies = 0
        self._last_sku = ""
        self._build_window()
        self._build_ui()
        self._create_overlay()
        self._create_engine()
        self.toast = Toast(root, self.m)
        self._refresh_model_bar()
        self._refresh_primary()
        self._refresh_stats(0, 0)
        self._set_phase("idle")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self._report_callback_exception
        self.root.after(80, self._poll_events)
        self.root.after(35, self._poll_ui_requests)
        self.root.after(80, self._poll_hotkeys)
        self._install_hotkeys()
        self.root.after(200, self._first_run_hint)

    # ---- window / chrome -------------------------------------------------------
    def _build_window(self):
        m = self.m
        self.root.title(APP_NAME)
        self.root.configure(bg=theme.BG)
        self.root.resizable(False, False)
        icon = config_mod.resource_path("assets", "icon.ico")
        try:
            if icon.exists():
                self.root.iconbitmap(default=str(icon))
        except Exception:
            log.debug("Could not set window icon", exc_info=True)
        w, h = m.px(430), m.px(748)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = self.cfg.data.get("ui", {}).get("x")
        y = self.cfg.data.get("ui", {}).get("y")
        if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0 or x > sw - m.px(180) or y > sh - m.px(180):
            x, y = m.px(26), m.px(52)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.update_idletasks()
        try:
            hwnd = _top_hwnd(self.root.winfo_id())
            winutil.apply_dark_titlebar(hwnd)
            winutil.apply_rounded_corners(hwnd)
        except Exception:
            pass

    def _build_ui(self):
        m = self.m
        self.container = tk.Frame(self.root, bg=theme.BG)
        self.container.pack(fill="both", expand=True, padx=m.px(20), pady=m.px(15))

        self._build_header()
        self._build_status_card()
        self._build_model_bar()
        self._build_primary()
        self._build_controls()
        self._build_preview()
        self._build_footer()

    def _build_header(self):
        m = self.m
        header = tk.Frame(self.container, bg=theme.BG)
        header.pack(fill="x")
        logo = tk.Canvas(header, width=m.px(44), height=m.px(44), bg=theme.BG, bd=0, highlightthickness=0)
        logo.pack(side="left")
        rounded_rect(logo, 1, 1, m.px(43), m.px(43), m.px(12), fill=theme.ACCENT_DARK, outline="")
        logo.create_text(m.px(22), m.px(22), text="解", fill=theme.WHITE, font=m.font(18, "bold"))

        titles = tk.Frame(header, bg=theme.BG)
        titles.pack(side="left", padx=(m.px(12), 0), fill="x", expand=True)
        tk.Label(
            titles, text="屏幕解答", bg=theme.BG, fg=theme.TEXT, font=m.font(17, "bold"), anchor="w"
        ).pack(fill="x")
        tk.Label(
            titles,
            text="SCREEN ANSWER  ·  每 5 秒自动读屏",
            bg=theme.BG,
            fg=theme.MUTED_DARK,
            font=m.font(7.5),
            anchor="w",
        ).pack(fill="x", pady=(m.px(2), 0))

        self.settings_btn = HoverButton(
            header,
            m,
            "设置",
            self.show_settings,
            bg=theme.CARD,
            fg=theme.TEXT_SOFT,
            hover_bg=theme.CARD_HOVER,
            font_size=9,
            padx=13,
            pady=7,
        )
        self.settings_btn.pack(side="right", pady=(m.px(4), 0))

    def _build_status_card(self):
        m = self.m
        self.status_card = Card(self.container, m, padding=14)
        self.status_card.pack(fill="x", pady=(m.px(14), 0))
        body = self.status_card.body
        body.grid_columnconfigure(0, weight=1)
        left = tk.Frame(body, bg=theme.CARD)
        left.grid(row=0, column=0, sticky="w")
        row = tk.Frame(left, bg=theme.CARD)
        row.pack(fill="x")
        self.status_dot = Dot(row, m, theme.MUTED, size=10, bg=theme.CARD)
        self.status_dot.pack(side="left", padx=(0, m.px(9)))
        self.status_title = tk.Label(
            row, text="待机中", bg=theme.CARD, fg=theme.TEXT, font=m.font(13, "bold"), anchor="w"
        )
        self.status_title.pack(side="left")
        self.status_sub = tk.Label(
            left,
            text="点「开始监测」，或按 F8",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=m.font(8.5),
            anchor="w",
            justify="left",
            wraplength=m.px(270),
        )
        self.status_sub.pack(fill="x", pady=(m.px(5), 0))

        count = tk.Frame(body, bg=theme.CARD)
        count.grid(row=0, column=1, sticky="e", padx=(m.px(10), 0))
        self.count_value = tk.Label(
            count, text="0", bg=theme.CARD, fg=theme.ACCENT, font=m.font(20, "bold"), anchor="e"
        )
        self.count_value.pack(anchor="e")
        self.count_caption = tk.Label(
            count, text="已解答", bg=theme.CARD, fg=theme.MUTED_DARK, font=m.font(8), anchor="e"
        )
        self.count_caption.pack(anchor="e")

    def _build_model_bar(self):
        m = self.m
        self.model_bar = tk.Frame(self.container, bg=theme.AMBER_DARK, cursor="hand2", bd=0, highlightthickness=0)
        self.model_bar.pack(fill="x", pady=(m.px(10), 0))
        inner = tk.Frame(self.model_bar, bg=theme.AMBER_DARK)
        inner.pack(fill="x", padx=m.px(11), pady=m.px(8))
        self.model_dot = tk.Label(inner, text="●", bg=theme.AMBER_DARK, fg=theme.AMBER, font=m.font(7))
        self.model_dot.pack(side="left")
        self.model_label = tk.Label(
            inner,
            text="还没配置模型 API · 点这里填写 →",
            bg=theme.AMBER_DARK,
            fg="#FDE68A",
            font=m.font(8.5),
            anchor="w",
        )
        self.model_label.pack(side="left", padx=(m.px(8), 0), fill="x", expand=True)
        for widget in (self.model_bar, inner, self.model_dot, self.model_label):
            widget.bind("<Button-1>", lambda _e: self.show_settings())
            widget.configure(cursor="hand2")

    def _build_primary(self):
        m = self.m
        self.primary_btn = HoverButton(
            self.container,
            m,
            "开始监测    F8",
            self.toggle_monitor,
            bg=theme.ACCENT,
            fg=theme.ACCENT_TEXT,
            hover_bg=theme.ACCENT_HOVER,
            font_size=11,
            bold=True,
            pady=12,
        )
        self.primary_btn.pack(fill="x", pady=(m.px(12), 0))

    def _build_controls(self):
        m = self.m
        card = Card(self.container, m, padding=14)
        card.pack(fill="x", pady=(m.px(12), 0))
        b = card.body

        row1 = tk.Frame(b, bg=theme.CARD)
        row1.pack(fill="x")
        tk.Label(row1, text="检查间隔", bg=theme.CARD, fg=theme.TEXT_SOFT, font=m.font(9), anchor="w").pack(side="left")
        right1 = tk.Frame(row1, bg=theme.CARD)
        right1.pack(side="right")
        self.minus_btn = HoverButton(
            right1, m, "−", lambda: self._change_interval(-1),
            bg=theme.PANEL, fg=theme.MUTED, hover_bg=theme.CARD_HOVER,
            font_size=12, padx=8, pady=1,
        )
        self.minus_btn.pack(side="left")
        self.interval_label = tk.Label(
            right1, text=f"{self.cfg.interval} 秒", bg=theme.CARD, fg=theme.TEXT,
            font=m.font(10, "bold"), width=5, anchor="center",
        )
        self.interval_label.pack(side="left", padx=m.px(4))
        self.plus_btn = HoverButton(
            right1, m, "+", lambda: self._change_interval(1),
            bg=theme.PANEL, fg=theme.MUTED, hover_bg=theme.CARD_HOVER,
            font_size=12, padx=8, pady=1,
        )
        self.plus_btn.pack(side="left")

        self._sep(b)

        row2 = tk.Frame(b, bg=theme.CARD)
        row2.pack(fill="x")
        tk.Label(row2, text="读取范围", bg=theme.CARD, fg=theme.TEXT_SOFT, font=m.font(9), anchor="w").pack(side="left")
        right2 = tk.Frame(row2, bg=theme.CARD)
        right2.pack(side="right")
        self.region_link = LinkLabel(
            right2,
            m,
            "重新框选" if self.cfg.region else "框选题目",
            self.select_region,
            bg=theme.CARD,
            font_size=8.5,
        )
        self.region_link.pack(side="right", padx=(m.px(10), 0))
        self.mode_seg = Segmented(
            right2,
            m,
            [("full", "全屏"), ("region", "选区")],
            self._on_mode_change,
            bg=theme.CARD,
            selected=self.cfg.capture.get("mode", "full"),
        )
        self.mode_seg.pack(side="right")

        self._sep(b)

        row3 = tk.Frame(b, bg=theme.CARD)
        row3.pack(fill="x")
        tk.Label(row3, text="上次读取", bg=theme.CARD, fg=theme.TEXT_SOFT, font=m.font(9), anchor="w").pack(side="left")
        self.last_read_label = tk.Label(
            row3, text="—", bg=theme.CARD, fg=theme.MUTED, font=m.font(8.5), anchor="w"
        )
        self.last_read_label.pack(side="left", padx=(m.px(10), 0))
        self.skip_label = tk.Label(
            row3, text="", bg=theme.CARD, fg=theme.MUTED_DARK, font=m.font(8), anchor="e"
        )
        self.skip_label.pack(side="right")

    def _sep(self, parent):
        tk.Frame(parent, bg=theme.BORDER_SOFT, height=1).pack(fill="x", pady=self.m.px(9))

    def _build_preview(self):
        m = self.m
        card = Card(self.container, m, padding=12)
        card.pack(fill="x", pady=(m.px(12), 0))
        b = card.body
        head = tk.Frame(b, bg=theme.CARD)
        head.pack(fill="x")
        tk.Label(head, text="读取预览", bg=theme.CARD, fg=theme.TEXT_SOFT, font=m.font(9), anchor="w").pack(side="left")
        badge = tk.Label(
            head, text="本机 OCR", bg=theme.GREEN_DARK, fg=theme.GREEN,
            font=m.font(7.5), padx=m.px(7), pady=m.px(2),
        )
        badge.pack(side="right")

        self.preview_canvas = tk.Canvas(
            b, bg="#091321", height=m.px(112), bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER_SOFT,
        )
        self.preview_canvas.pack(fill="x", pady=(m.px(8), 0))
        self.preview_canvas.bind("<Configure>", lambda _e: self._redraw_placeholder())

        foot = tk.Frame(b, bg=theme.CARD)
        foot.pack(fill="x", pady=(m.px(6), 0))
        self.preview_caption = tk.Label(
            foot, text="等待第一次读取", bg=theme.CARD, fg=theme.MUTED_DARK,
            font=m.font(7.8), anchor="w",
        )
        self.preview_caption.pack(side="left", fill="x", expand=True)
        self.char_label = tk.Label(
            foot, text="", bg=theme.CARD, fg=theme.MUTED_DARK, font=m.font(7.8), anchor="e"
        )
        self.char_label.pack(side="right")

    def _build_footer(self):
        m = self.m
        foot = tk.Frame(self.container, bg=theme.BG)
        foot.pack(fill="x", pady=(m.px(11), 0))
        left = tk.Frame(foot, bg=theme.BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(
            left,
            text="F8 开始 / 暂停    F9 立即识别    F10 浮窗",
            bg=theme.BG,
            fg=theme.MUTED,
            font=m.font(7.8),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            left,
            text="OCR 在本机运行 · 截图默认不保存",
            bg=theme.BG,
            fg=theme.MUTED_DARK,
            font=m.font(7.2),
            anchor="w",
        ).pack(fill="x", pady=(m.px(2), 0))
        LinkLabel(foot, m, "使用说明", self._show_help, bg=theme.BG, font_size=8).pack(side="right", anchor="s")

    # ---- overlay / engine ------------------------------------------------------
    def _create_overlay(self):
        m = self.m
        ow = m.px(self.cfg.overlay.get("width", 470))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = self.cfg.overlay.get("x")
        y = self.cfg.overlay.get("y")
        if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0 or x > sw - m.px(160) or y > sh - m.px(160):
            x, y = sw - ow - m.px(36), m.px(96)
        self.overlay = AnswerOverlay(
            self.root,
            m,
            self.cfg,
            x=x,
            y=y,
            on_copy=self._copy_answer,
            on_retry=self.capture_now,
            on_settings=self.show_settings,
            on_moved=self._overlay_moved,
        )

    def _create_engine(self):
        bridge = UiBridge(self.call_ui)
        self.engine = MonitorEngine(self.cfg, bridge, self.events)
        self.engine.attach_app(self)

    # ---- thread bridges --------------------------------------------------------
    def call_ui(self, fn: Callable[[], Any], timeout: float = 3.0, default=None):
        if threading.current_thread() is threading.main_thread():
            try:
                return fn()
            except Exception:
                log.exception("UI call failed")
                return default
        if self._closing:
            return default
        box: dict[str, Any] = {}
        done = threading.Event()
        try:
            self._ui_queue.put_nowait((fn, box, done))
        except queue.Full:
            return default
        if done.wait(timeout):
            return box.get("value", default)
        return default

    def _poll_ui_requests(self):
        if self._closing:
            return
        for _ in range(30):
            try:
                fn, box, done = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                box["value"] = fn()
            except Exception:
                log.exception("UI request failed")
            finally:
                done.set()
        self.root.after(35, self._poll_ui_requests)

    # ---- window hide/restore for a clean capture ------------------------------
    def _own_windows(self):
        windows = [self.root, self.overlay.win]
        if self.settings_dialog is not None:
            windows.append(self.settings_dialog.win)
        out = []
        for win in windows:
            try:
                if win.winfo_exists() and win.winfo_viewable() and win.state() != "iconic":
                    out.append(win)
            except Exception:
                pass
        return out

    def own_window_rects(self):
        rects = []
        for win in self._own_windows():
            try:
                rect = winutil.window_rect(_top_hwnd(win.winfo_id()))
                if not rect or rect[2] < 2 or rect[3] < 2:
                    rect = (win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height())
                x, y, w, h = rect
                pad = self.m.px(3)
                rects.append((x - pad, y - pad, w + pad * 2, h + pad * 2))
            except Exception:
                pass
        return rects

    # ---- status / chrome ------------------------------------------------------
    def _set_phase(self, phase: str, message: str | None = None):
        self._last_phase = phase
        titles = {
            "idle": ("待机中", theme.MUTED, "点「开始监测」，或按 F8"),
            "starting": ("启动中", theme.ACCENT, "正在准备读取屏幕…"),
            "watching": ("监测中", theme.GREEN, f"每 {self.cfg.interval} 秒检查一次 · 画面变化才会请求模型"),
            "capturing": ("读取中", theme.ACCENT, "发现画面变化，正在截取干净画面…"),
            "ocr": ("识别中", theme.ACCENT, "正在用 Windows OCR 读取文字…"),
            "thinking": ("求解中", theme.AMBER, "题目已发给模型，等待回答…"),
            "paused": ("已暂停", theme.MUTED, "按 F8 或点「开始监测」继续"),
            "needs_setup": ("待配置", theme.AMBER, "没有模型 API，只会识别文字；点上方横条填写"),
            "ocr_only": ("识图模式", theme.ACCENT, "识别到新文字会自动复制，不调用 API"),
            "error": ("出错了", theme.RED, "看一下浮窗里的提示，或重试"),
        }
        title, color, sub = titles.get(phase, ("监测中", theme.GREEN, ""))
        if message:
            sub = message
        self.status_title.configure(text=title, fg=theme.TEXT)
        self.status_dot.set_color(color)
        self.status_sub.configure(text=sub)
        self._refresh_primary()

    def _refresh_primary(self):
        running = False
        try:
            running = self.engine.running
        except Exception:
            pass
        if running:
            self.primary_btn.set_text("暂停监测    F8")
            self.primary_btn.set_colors("#3B1E28", "#FCA5A5", hover_bg="#4A2531")
        else:
            self.primary_btn.set_text("开始监测    F8")
            self.primary_btn.set_colors(theme.ACCENT, theme.ACCENT_TEXT, hover_bg=theme.ACCENT_HOVER)

    def _refresh_stats(self, answers: int, skips: int):
        if self.cfg.ocr_only:
            self.count_caption.configure(text="已识别")
            self.count_value.configure(text=str(self._ocr_copies))
        else:
            self.count_caption.configure(text="已解答")
            self.count_value.configure(text=str(answers))
        if skips:
            self.skip_label.configure(text=f"已跳过 {skips} 次")
        else:
            self.skip_label.configure(text="")

    def _refresh_model_bar(self):
        if self.cfg.ocr_only:
            bg, fg, dot = theme.CARD, theme.TEXT_SOFT, theme.ACCENT
            if self.cfg.region and self.cfg.capture.get("mode") == "region":
                text = "识图模式 · 已框选题目区域 · 自动复制文字"
            else:
                text = "识图模式 · 建议框选题目区域，减少干扰"
        elif self.cfg.needs_key and not self.cfg.get_api_key():
            bg, fg, dot = theme.AMBER_DARK, "#FDE68A", theme.AMBER
            text = "还没配置模型 API · 点这里填写 →"
        else:
            bg, fg, dot = theme.CARD, theme.MUTED, theme.GREEN
            model = str(self.cfg.api.get("model") or "未选模型")
            mode = "视觉 + OCR" if self.cfg.api.get("vision") else "OCR 文字"
            text = f"{self.cfg.provider} · {model} · {mode}"
            text = text[:64]
        self.model_bar.configure(bg=bg)
        for child in self.model_bar.winfo_children():
            child.configure(bg=bg)
            for sub in child.winfo_children():
                try:
                    sub.configure(bg=bg)
                except Exception:
                    pass
        self.model_label.configure(text=text, fg=fg)
        self.model_dot.configure(fg=dot, bg=bg)
        self._refresh_primary()

    def _first_run_hint(self):
        if self.cfg.ocr_only:
            self.toast.show("识图模式：识别到文字会自动复制，不调用 API", 3800)
        elif not self.cfg.has_api_key():
            self.toast.show("先点上方横条填 API Key，F8 才开始自动解答", 4200)

    def _change_interval(self, delta: int):
        value = max(2, min(120, self.cfg.interval + delta))
        if value == self.cfg.interval:
            return
        self.cfg.capture["interval"] = value
        self.interval_label.configure(text=f"{value} 秒")
        try:
            self.cfg.save()
        except Exception:
            pass
        self.overlay.set_interval(value)
        if self._last_phase == "watching":
            self._set_phase("watching")

    def _on_mode_change(self, mode: str):
        if mode == "region" and self.cfg.region is None:
            self._last_mode = self.cfg.capture.get("mode", "full")
            self.mode_seg.set(self._last_mode)
            self.select_region()
            return
        self.cfg.capture["mode"] = mode
        self._last_mode = mode
        self._refresh_model_bar()
        if mode == "full":
            self.region_link.configure(text="重新框选" if self.cfg.region else "框选题目")
        try:
            self.cfg.save()
        except Exception:
            pass
        self.engine.reset()
        self.toast.show("已切换为框选区域" if mode == "region" else "已切换为全屏读取", 1600)

    # ---- actions ---------------------------------------------------------------
    def toggle_monitor(self):
        if self.engine.running:
            self.engine.pause()
            self._set_phase("paused")
        else:
            self.start_monitor()

    def start_monitor(self):
        if self.cfg.capture.get("mode") == "region" and self.cfg.region is None:
            self.select_region(start_after=True)
            return
        if (
            self.cfg.ocr_only
            and self.cfg.region is None
            and not self.cfg.behavior.get("ocr_region_prompted")
        ):
            self.cfg.behavior["ocr_region_prompted"] = True
            try:
                self.cfg.save()
            except Exception:
                pass
            choice = messagebox.askyesno(
                "识图模式",
                "识图模式建议先框选题目区域，可以明显减少桌面图标、浏览器地址栏等杂字。\n\n"
                "现在框选题目区域吗？\n"
                "选择「否」会读取整个屏幕。",
                parent=self.root,
            )
            if choice:
                self.select_region(start_after=True)
                return
        if not self.cfg.ocr_only and not self.cfg.has_api_key():
            self.toast.show("还没填 API Key，启动后只会识别文字；可在设置里开启识图模式", 3200)
        self.engine.start()
        self._set_phase("starting")
        self.root.after(100, self._refresh_primary)
        if self.cfg.behavior.get("auto_minimize"):
            self.root.after(1400, self._maybe_minimize)

    def _maybe_minimize(self):
        try:
            if self.engine.running and self.root.state() != "iconic":
                self.root.iconify()
        except Exception:
            pass

    def pause_monitor(self):
        self.engine.pause()
        self._set_phase("paused")

    def capture_now(self):
        if not self.engine.running:
            self.start_monitor()
            if not self.engine.running:
                return
        self.engine.force_capture()
        self._set_phase("capturing", "正在重新读取当前屏幕…")

    def select_region(self, start_after: bool = False):
        if self.region_selector is not None:
            return
        self.overlay.hide()
        self.region_selector = RegionSelector(
            self.root,
            self.m,
            lambda region: self._region_done(region, start_after),
        )

    def _region_done(self, region, start_after: bool):
        self.region_selector = None
        if region is None:
            self._set_phase("idle", "已取消框选")
            self.mode_seg.set(self.cfg.capture.get("mode", "full"))
            return
        self.cfg.set_region(region)
        self.cfg.capture["mode"] = "region"
        self._last_mode = "region"
        try:
            self.cfg.save()
        except Exception:
            pass
        self.mode_seg.set("region")
        self.region_link.configure(text="重新框选")
        self._refresh_model_bar()
        self.engine.reset()
        self.toast.show(f"已框选 {region[2]} × {region[3]} 区域", 1800)
        self._set_phase("idle", "选区已保存，按 F8 开始读取")
        if start_after:
            self.start_monitor()

    def show_settings(self):
        if self.settings_dialog is not None:
            try:
                self.settings_dialog.win.lift()
                self.settings_dialog.win.focus_force()
            except Exception:
                pass
            return
        self._overlay_was_visible = self.overlay.is_visible()
        self.overlay.auto_show = False
        if self._overlay_was_visible:
            self.overlay.hide()
        self.settings_dialog = SettingsDialog(
            self.root,
            self.cfg,
            self.m,
            on_saved=self._settings_saved,
            on_closed=self._settings_closed,
            first_run=not self.cfg.has_api_key(),
        )

    def _settings_saved(self):
        self._refresh_model_bar()
        self.overlay.set_interval(self.cfg.interval)
        self.engine.reset()
        if self.cfg.ocr_only:
            self.count_caption.configure(text="已识别")
            self.count_value.configure(text=str(self._ocr_copies))
        else:
            self.count_caption.configure(text="已解答")
            self.count_value.configure(text=str(self.engine.answer_count))
        self.toast.show("设置已保存", 1800)
        if not self.engine.running:
            self._set_phase("idle", "设置已保存，按 F8 开始读取")

    def _settings_closed(self):
        self.settings_dialog = None
        self.overlay.auto_show = True
        if self._overlay_was_visible:
            try:
                self.overlay._safe_show(force=True)
            except Exception:
                pass
        self._overlay_was_visible = False

    def _overlay_moved(self, x: int, y: int):
        self.cfg.overlay["x"] = int(x)
        self.cfg.overlay["y"] = int(y)
        try:
            self.cfg.save()
        except Exception:
            pass

    def _copy_answer(self, text: str):
        self._copy_text(text, announce=False)
        self.overlay.flash_status("已复制", theme.GREEN)
        self.toast.show("答案已复制", 1500)

    def _copy_text(self, text: str, announce: bool = True):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
            if announce:
                self.toast.show("已复制到剪贴板", 1500)
        except Exception:
            if announce:
                self.toast.show("复制失败", 1600)

    def _show_help(self):
        was_visible = self.overlay.is_visible()
        if was_visible:
            self.overlay.hide()
        try:
            messagebox.showinfo(
                "使用说明",
                "1. 点右上角「设置」，选择一个服务商并填入 API Key（Ollama 本地模型不需要 Key）。\n\n"
                "2. 建议点「框选」框住题目和选项，只读这一块；也可以直接用全屏。\n\n"
                "3. 点「开始监测」或按 F8。画面变化时自动识别并解答，答案出现在右侧浮窗。\n\n"
                "F9 立即识别当前屏幕，F10 显示 / 隐藏浮窗。\n\n"
                "隐私：OCR 在本机完成，截图默认不保存；只有开启视觉模式时，题目区域截图才会发送给你配置的模型服务。\n\n"
                "请用于学习自查，并遵守课程和考试规则。",
                parent=self.root,
            )
        finally:
            if was_visible:
                self.overlay._safe_show(force=True)

    # ---- hotkeys ---------------------------------------------------------------
    def _install_hotkeys(self):
        VK_F8, VK_F9, VK_F10 = 0x77, 0x78, 0x79
        self._hotkey_manager = winutil.HotkeyManager(
            {
                1: (VK_F8, lambda: self._hotkey_queue.put("toggle")),
                2: (VK_F9, lambda: self._hotkey_queue.put("capture")),
                3: (VK_F10, lambda: self._hotkey_queue.put("overlay")),
            },
            on_error=lambda failures: self._hotkey_queue.put(("error", failures)),
        )
        self._hotkey_manager.start()

    def _poll_hotkeys(self):
        if self._closing:
            return
        for _ in range(10):
            try:
                action = self._hotkey_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(action, tuple) and action[0] == "error":
                names = "、".join(name for name, _ in action[1])
                self.toast.show(f"{names} 热键被其他程序占用", 2600)
                continue
            if action == "toggle":
                self.toggle_monitor()
            elif action == "capture":
                self.capture_now()
            elif action == "overlay":
                self.overlay.toggle()
        self.root.after(80, self._poll_hotkeys)

    # ---- events ----------------------------------------------------------------
    def _poll_events(self):
        if self._closing:
            return
        for _ in range(40):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(event)
            except Exception:
                log.exception("Could not handle monitor event: %s", event.get("type"))
        self.root.after(60, self._poll_events)

    def _handle_event(self, event: dict):
        kind = event.get("type")
        if kind == "status":
            phase = event.get("phase", "watching")
            message = event.get("message")
            if phase == "error" and self._last_phase == "error":
                return
            if phase == "paused" and self._last_phase == "error":
                return
            self._set_phase(phase, message)
        elif kind == "stats":
            self._refresh_stats(int(event.get("answers", 0)), int(event.get("skips", 0)))
        elif kind == "frame":
            image = event.get("image")
            at = event.get("at") or datetime.now()
            if image is not None:
                self._render_preview(image, at)
            self.last_read_label.configure(text=at.strftime("%H:%M:%S"))
            self.preview_caption.configure(text=f"读取于 {at.strftime('%H:%M:%S')}")
        elif kind == "skip":
            self._refresh_stats(self.engine.answer_count, self.engine.skip_count)
            reason = event.get("reason")
            if reason == "unchanged":
                self.preview_caption.configure(text="画面未变化，本次不请求模型")
            elif reason == "same_text":
                self.preview_caption.configure(text="题目没变，跳过重复请求")
            elif reason == "backoff":
                self.preview_caption.configure(text="上次请求出错，稍后自动重试")
        elif kind == "ocr":
            chars = int(event.get("chars", 0))
            focus = bool(event.get("focus"))
            self.char_label.configure(text=f"{chars} 字")
            self.preview_caption.configure(
                text=("已锁定题目区域" if focus else "已识别屏幕文字") + f" · {chars} 字"
            )
        elif kind == "ocr_text":
            text = str(event.get("text", ""))
            self._copy_text(text, announce=False)
            self.overlay.show_ocr_text(text)
            self._set_phase("ocr_only")
            self._ocr_copies += 1
            self.count_caption.configure(text="已识别")
            self.count_value.configure(text=str(self._ocr_copies))
            self.preview_caption.configure(text="识图模式：文字已识别并复制，不调用 API")
            self.toast.show("识别到的文字已复制到剪贴板", 2200)
        elif kind == "analyzing":
            self.overlay.show_analyzing(str(event.get("text", "")))
            self._set_phase("thinking")
        elif kind == "delta":
            self.overlay.append_stream(str(event.get("text", "")))
        elif kind == "done":
            text = str(event.get("text", ""))
            meta_bits = []
            if event.get("elapsed") is not None:
                meta_bits.append(f"{event['elapsed']}s")
            if event.get("model"):
                meta_bits.append(str(event["model"]))
            self.overlay.show_answer(text, " · ".join(meta_bits))
            self.count_caption.configure(text="已解答")
            self._refresh_stats(self.engine.answer_count, self.engine.skip_count)
            self.preview_caption.configure(text="解答完成，继续监测画面变化")
        elif kind == "error":
            message = str(event.get("message", "未知错误"))
            self.overlay.show_error(message)
            self._set_phase("error", message[:100])
        elif kind == "needs_setup":
            self.overlay.show_needs_setup(str(event.get("text", "")))
            self._set_phase("needs_setup")
            self._refresh_model_bar()
        elif kind == "warning":
            self.toast.show(str(event.get("message", "")), 2600)

    def _render_preview(self, image: Image.Image, at: datetime):
        try:
            cw = self.preview_canvas.winfo_width()
            ch = self.preview_canvas.winfo_height()
            if cw < 60 or ch < 40:
                cw, ch = self.m.px(360), self.m.px(112)
            fitted = ImageOps.fit(image.convert("RGB"), (cw, ch), method=Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(fitted)
            self._preview_photo = photo
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(0, 0, anchor="nw", image=photo)
            pad = self.m.px(7)
            badge_w = self.m.px(62)
            badge_h = self.m.px(19)
            x = cw - badge_w - pad
            y = ch - badge_h - pad
            self.preview_canvas.create_rectangle(
                x, y, x + badge_w, y + badge_h, fill="#0B1220", outline=""
            )
            self.preview_canvas.create_text(
                x + badge_w // 2, y + badge_h // 2,
                text=at.strftime("%H:%M:%S"), fill=theme.TEXT_SOFT, font=self.m.font(7.5),
            )
        except Exception:
            log.debug("Preview render failed", exc_info=True)

    def _redraw_placeholder(self):
        if self._preview_photo is not None:
            return
        c = self.preview_canvas
        try:
            c.delete("all")
            cw = c.winfo_width() or self.m.px(360)
            ch = c.winfo_height() or self.m.px(112)
            c.create_text(
                cw // 2, ch // 2 - self.m.px(7),
                text="开始后在这里显示读取到的画面",
                fill=theme.MUTED,
                font=self.m.font(8.5),
            )
            c.create_text(
                cw // 2, ch // 2 + self.m.px(14),
                text="画面没变化时不会调用模型",
                fill=theme.MUTED_DARK,
                font=self.m.font(7.5),
            )
        except Exception:
            pass

    # ---- lifecycle -------------------------------------------------------------
    def _report_callback_exception(self, exc, val, tb):
        log.error("Tk callback exception", exc_info=(exc, val, tb))
        try:
            self.toast.show("界面出现异常，详情见 logs/app.log", 2600)
        except Exception:
            pass

    def _save_positions(self):
        try:
            self.root.update_idletasks()
            ox, oy = self.overlay.position()
            self.cfg.save_window_positions(self.root.winfo_x(), self.root.winfo_y(), ox, oy)
        except Exception:
            pass

    def close(self):
        if self._closing:
            return
        self._closing = True
        try:
            self._save_positions()
        except Exception:
            pass
        try:
            if self._hotkey_manager:
                self._hotkey_manager.stop()
        except Exception:
            pass
        try:
            self.engine.shutdown()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
