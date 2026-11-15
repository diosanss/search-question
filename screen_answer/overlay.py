"""Always-on-top answer overlay that does not steal keyboard focus."""

from __future__ import annotations

import ctypes
import logging
import re
import tkinter as tk
from tkinter import ttk
from typing import Callable

from . import theme, winutil
from .config import Config
from .theme import Metrics

log = logging.getLogger(__name__)


def _top_hwnd(hwnd: int) -> int:
    try:
        user32 = ctypes.windll.user32
        parent = user32.GetParent(hwnd)
        current = hwnd
        for _ in range(12):
            if not parent:
                break
            current = parent
            parent = user32.GetParent(current)
        return current
    except Exception:
        return hwnd


class AnswerOverlay:
    def __init__(
        self,
        root: tk.Tk,
        metrics: Metrics,
        cfg: Config,
        *,
        x: int,
        y: int,
        on_copy: Callable[[str], None],
        on_retry: Callable[[], None],
        on_settings: Callable[[], None],
        on_moved: Callable[[int, int], None] | None = None,
    ):
        self.root = root
        self.m = metrics
        self.cfg = cfg
        self._on_copy = on_copy
        self._on_retry = on_retry
        self._on_settings = on_settings
        self._on_moved = on_moved
        self.last_answer = ""
        self.last_question = ""
        self._ocr_mode = False
        self.auto_show = True
        self._animating = False
        self._anim_after = None
        self._dot_count = 0
        self._status_serial = 0
        self._drag = None
        self._hwnd = None
        self._rounded_size = None

        w = metrics.px(cfg.overlay.get("width", 470))
        h = metrics.px(cfg.overlay.get("height", 430))
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.configure(bg=theme.BG)
        self.win.attributes("-topmost", True)
        # Keep the overlay non-layered. SetWindowDisplayAffinity is unreliable
        # on layered Tk windows, and a layered overlay would be captured by
        # mss (causing a feedback loop and a visible flash).
        self.win.minsize(metrics.px(340), metrics.px(260))
        self.win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")

        self.outer = tk.Frame(
            self.win,
            bg=theme.BG,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.BORDER,
            bd=0,
        )
        self.outer.pack(fill="both", expand=True)
        self.accent = tk.Frame(self.outer, bg=theme.ACCENT, width=metrics.px(3))
        self.accent.pack(side="left", fill="y")
        self.content = tk.Frame(self.outer, bg=theme.BG)
        self.content.pack(side="left", fill="both", expand=True)

        self._build_header()
        self._build_body()
        self._build_footer()

        self.win.bind("<Escape>", lambda _e: self.hide())
        self.win.bind("<Configure>", self._on_configure, add="+")
        self.win.after(80, self._init_window)
        self.show_idle()

    # ---- construction ----------------------------------------------------------
    def _build_header(self):
        m = self.m
        self.header = tk.Frame(self.content, bg=theme.BG)
        self.header.pack(fill="x", padx=m.px(16), pady=(m.px(12), m.px(9)))
        title_wrap = tk.Frame(self.header, bg=theme.BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        row = tk.Frame(title_wrap, bg=theme.BG)
        row.pack(fill="x")
        tk.Label(
            row,
            text="AI 解答",
            bg=theme.BG,
            fg=theme.TEXT,
            font=m.font(13, "bold"),
            anchor="w",
        ).pack(side="left")
        self.status_dot = tk.Canvas(row, width=m.px(8), height=m.px(8), bg=theme.BG, bd=0, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(m.px(10), m.px(5)))
        self._status_dot_item = self.status_dot.create_oval(1, 1, m.px(8) - 1, m.px(8) - 1, fill=theme.MUTED, outline="")
        self.status_label = tk.Label(
            row,
            text="等待读取",
            bg=theme.BG,
            fg=theme.MUTED,
            font=m.font(9),
            anchor="w",
        )
        self.status_label.pack(side="left")
        self.close_btn = tk.Label(
            self.header,
            text="×",
            bg=theme.BG,
            fg=theme.MUTED,
            font=m.font(15),
            cursor="hand2",
            padx=m.px(6),
            pady=0,
        )
        self.close_btn.pack(side="right")
        self.close_btn.bind("<Button-1>", lambda _e: self.hide())
        self.close_btn.bind("<Enter>", lambda _e: self.close_btn.configure(fg=theme.TEXT))
        self.close_btn.bind("<Leave>", lambda _e: self.close_btn.configure(fg=theme.MUTED))

        self.subtitle = tk.Label(
            title_wrap,
            text="每 5 秒检查一次 · 答案只在本机浮窗显示",
            bg=theme.BG,
            fg=theme.MUTED_DARK,
            font=m.font(8.5),
            anchor="w",
        )
        self.subtitle.pack(fill="x", pady=(m.px(3), 0))

        for widget in (self.header, title_wrap, row):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._end_drag)

        self.sep = tk.Frame(self.content, bg=theme.BORDER_SOFT, height=1)
        self.sep.pack(fill="x")

    def _build_body(self):
        m = self.m
        body_wrap = tk.Frame(self.content, bg=theme.BG)
        body_wrap.pack(fill="both", expand=True, padx=(m.px(16), m.px(8)), pady=(m.px(10), m.px(6)))

        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Overlay.Vertical.TScrollbar",
            background=theme.BORDER,
            troughcolor=theme.BG,
            bordercolor=theme.BG,
            arrowcolor=theme.MUTED,
            darkcolor=theme.BORDER,
            lightcolor=theme.BORDER,
            width=m.px(7),
        )
        style.map("Overlay.Vertical.TScrollbar", background=[("active", theme.MUTED_DARK)])

        self.text = tk.Text(
            body_wrap,
            wrap="word",
            height=1,
            width=1,
            bg=theme.BG,
            fg=theme.TEXT_SOFT,
            insertbackground=theme.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            font=m.font(10),
            spacing1=m.px(2),
            spacing3=m.px(4),
            cursor="arrow",
            state="disabled",
            selectbackground=theme.ACCENT_DARK,
            selectforeground=theme.WHITE,
        )
        self.text.pack(side="left", fill="both", expand=True)
        self.scroll = ttk.Scrollbar(
            body_wrap,
            orient="vertical",
            command=self.text.yview,
            style="Overlay.Vertical.TScrollbar",
        )
        self.scroll.pack(side="right", fill="y", padx=(m.px(2), 0))
        self.text.configure(yscrollcommand=self.scroll.set)
        self.text.tag_configure("h", foreground=theme.ACCENT, font=m.font(10, "bold"), spacing1=m.px(6), spacing3=m.px(3))
        self.text.tag_configure("body", foreground=theme.TEXT_SOFT, font=m.font(10), lmargin1=0, lmargin2=0)
        self.text.tag_configure("muted", foreground=theme.MUTED, font=m.font(9))
        self.text.tag_configure("error", foreground=theme.RED, font=m.font(10))
        self.text.tag_configure("code", foreground="#A5F3FC", background="#0A1526", font=self.m.mono(9), lmargin1=m.px(10), lmargin2=m.px(10), spacing1=2, spacing3=2)
        self.text.bind("<MouseWheel>", self._on_wheel)
        self.text.bind("<Button-4>", lambda e: self.text.yview_scroll(-3, "units"))
        self.text.bind("<Button-5>", lambda e: self.text.yview_scroll(3, "units"))

    def _build_footer(self):
        m = self.m
        self.footer_sep = tk.Frame(self.content, bg=theme.BORDER_SOFT, height=1)
        self.footer_sep.pack(fill="x", padx=m.px(16), pady=(m.px(2), 0))
        self.footer = tk.Frame(self.content, bg=theme.BG)
        self.footer.pack(fill="x", padx=m.px(12), pady=(m.px(7), m.px(10)))
        self.btn_copy = self._footer_button(self.footer, "复制", self._copy)
        self.btn_copy.pack(side="left", padx=(m.px(2), m.px(4)))
        self.btn_retry = self._footer_button(self.footer, "重答", self._retry)
        self.btn_retry.pack(side="left", padx=m.px(4))
        self.btn_settings = self._footer_button(self.footer, "设置", self._settings)
        self.btn_settings.pack(side="left", padx=m.px(4))
        self.footer_hint = tk.Label(
            self.footer,
            text="F10 隐藏",
            bg=theme.BG,
            fg=theme.MUTED_DARK,
            font=m.font(8),
        )
        self.footer_hint.pack(side="right", padx=(0, m.px(4)))

    def _footer_button(self, parent, text: str, command):
        btn = tk.Label(
            parent,
            text=text,
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.m.font(9),
            padx=self.m.px(12),
            pady=self.m.px(5),
            cursor="hand2",
        )
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e: btn.configure(bg=theme.CARD_HOVER, fg=theme.TEXT))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=theme.CARD, fg=theme.MUTED))
        return btn

    def _init_window(self):
        try:
            self.win.update_idletasks()
            self._hwnd = _top_hwnd(self.win.winfo_id())
            winutil.make_tool_window(self._hwnd)
            winutil.apply_rounded_corners(self._hwnd)
            self._rounded_size = (self.win.winfo_width(), self.win.winfo_height())
        except Exception:
            log.debug("Overlay window init failed", exc_info=True)

    # ---- state -----------------------------------------------------------------
    def _set_status(self, text: str, color: str):
        self._status_serial += 1
        self.status_label.configure(text=text, fg=color)
        self.status_dot.itemconfigure(self._status_dot_item, fill=color)

    def set_interval(self, seconds: int):
        if self.cfg.ocr_only:
            self.subtitle.configure(text=f"识图模式 · 每 {seconds} 秒检查一次，只做本地 OCR")
        else:
            self.subtitle.configure(text=f"每 {seconds} 秒检查一次 · 答案只在本机浮窗显示")

    def flash_status(self, text: str, color: str = theme.GREEN):
        self._stop_animation()
        self._set_status(text, color)
        token = self._status_serial

        def restore():
            if token == self._status_serial and not self._animating:
                self._set_status("完成" if self.last_answer else "等待读取", theme.GREEN if self.last_answer else theme.MUTED)

        self.win.after(1600, restore)

    def _stop_animation(self):
        self._animating = False
        if self._anim_after:
            try:
                self.win.after_cancel(self._anim_after)
            except Exception:
                pass
            self._anim_after = None

    def _animate(self):
        if not self._animating:
            return
        self._dot_count = (self._dot_count + 1) % 4
        self.status_label.configure(text="正在分析" + "·" * self._dot_count)
        self._anim_after = self.win.after(420, self._animate)

    def _render(self, raw: str, *, scroll_top: bool = False, keep_scroll: bool = False):
        near_bottom = True
        try:
            near_bottom = self.text.yview()[1] >= 0.94
        except Exception:
            pass
        text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        in_code = False
        for line in text.split("\n"):
            stripped = line.rstrip()
            if stripped.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.text.insert("end", line + "\n", "code")
                continue
            if not stripped:
                self.text.insert("end", "\n", "body")
                continue
            clean = stripped.replace("**", "").replace("__", "")
            if re.match(r"^\s*#{1,4}\s*", clean):
                clean = re.sub(r"^\s*#{1,4}\s*", "", clean)
            if re.match(r"^\s*(答案|解析|结论|思路|正确答案|Answer)\s*[:：]?", clean, re.IGNORECASE) or re.match(
                r"^\s*(第?\s*\d+\s*[题.、．])", clean
            ):
                self.text.insert("end", clean + "\n", "h")
            elif re.match(r"^\s*[-*•]\s+", clean):
                self.text.insert("end", "  • " + re.sub(r"^\s*[-*•]\s+", "", clean) + "\n", "body")
            else:
                self.text.insert("end", clean + "\n", "body")
        self.text.configure(state="disabled")
        if scroll_top:
            self.text.see("1.0")
        elif (keep_scroll and near_bottom) or near_bottom:
            self.text.see("end")

    def _safe_show(self, force: bool = False):
        if not force and not self.auto_show:
            return
        try:
            self.win.deiconify()
            self.win.update_idletasks()
            if self._hwnd is None:
                self._init_window()
            size = (self.win.winfo_width(), self.win.winfo_height())
            self._rounded_size = size
            winutil.show_no_activate(self._hwnd)
        except Exception:
            log.debug("Overlay show failed", exc_info=True)

    # ---- public states ---------------------------------------------------------
    def _set_ocr_mode(self, enabled: bool):
        self._ocr_mode = enabled
        self.btn_copy.configure(text="复制文字" if enabled else "复制")
        self.btn_retry.configure(text="重新识图" if enabled else "重答")

    def show_idle(self):
        self._stop_animation()
        if self.cfg.ocr_only:
            self._set_ocr_mode(True)
            self._set_status("识图模式", theme.ACCENT)
            self.subtitle.configure(text=f"识图模式 · 每 {self.cfg.interval} 秒检查一次，只做本地 OCR")
            self._render(
                "识图模式：只在本机做 OCR，不调用任何 API、不需要 Key。\n\n"
                "点「开始监测」后，识别到新文字会自动复制到剪贴板，并显示在这里。\n\n"
                "F8 开始 / 暂停    F9 立即识图    F10 显示 / 隐藏",
                scroll_top=True,
            )
            return
        self._set_ocr_mode(False)
        self._set_status("等待读取", theme.MUTED)
        self.subtitle.configure(text=f"每 {self.cfg.interval} 秒检查一次 · 答案只在本机浮窗显示")
        self._render(
            "点「开始监测」后，程序会每隔几秒读取一次屏幕。\n\n"
            "检测到题目变化时，答案会自动出现在这里。\n\n"
            "F8 开始 / 暂停    F9 立即识别    F10 显示 / 隐藏",
            scroll_top=True,
        )

    def show_analyzing(self, question: str):
        self._stop_animation()
        self._set_ocr_mode(False)
        self.last_answer = ""
        self._dot_count = 0
        self._animating = True
        self._set_status("正在分析", theme.AMBER)
        self._animate()
        excerpt = (question or "").strip()
        if len(excerpt) > 420:
            excerpt = excerpt[:420] + "…"
        self._render("题目已读取：\n\n" + excerpt + "\n\n正在生成解答…", scroll_top=True)
        self._safe_show()

    def append_stream(self, text: str):
        self._stop_animation()
        self._set_status("正在生成", theme.ACCENT)
        self._render(text, keep_scroll=True)

    def show_answer(self, text: str, meta: str = ""):
        self._stop_animation()
        self._set_ocr_mode(False)
        self.last_answer = text
        self._set_status("完成" + (f" · {meta}" if meta else ""), theme.GREEN)
        self._render(text, scroll_top=True)
        self._safe_show()

    def show_error(self, message: str):
        self._stop_animation()
        self._set_ocr_mode(self.cfg.ocr_only)
        self.last_answer = ""
        self._set_status("出错", theme.RED)
        body = message.strip()
        body += "\n\n——\n• 检查右上角「设置」里的模型配置\n• 按 F9 可以立即重试当前屏幕"
        self._render(body, scroll_top=True)
        self._safe_show()

    def show_needs_setup(self, ocr_text: str):
        self._stop_animation()
        self._set_ocr_mode(False)
        self.last_answer = ""
        self.last_question = ocr_text
        self._set_status("未配置模型", theme.AMBER)
        excerpt = (ocr_text or "").strip()
        if len(excerpt) > 900:
            excerpt = excerpt[:900] + "\n……"
        body = (
            "已经从屏幕上读到了题目，但还没有配置模型 API，所以暂时不能生成答案。\n\n"
            "点下方的「设置」，填入任意 OpenAI 兼容接口的 API Key 即可；\n"
            "或者开启「识图模式」，只复制题目文字、不调用 API。\n\n"
            "识别到的题目：\n" + (excerpt or "（没有识别到文字，试试框选题目区域）")
        )
        self._render(body, scroll_top=True)
        self._safe_show()

    def show_ocr_text(self, text: str):
        self._stop_animation()
        self._set_ocr_mode(True)
        self.last_answer = ""
        self.last_question = text
        self._set_status("已识别并复制", theme.GREEN)
        self.subtitle.configure(text=f"识图模式 · 每 {self.cfg.interval} 秒检查一次，只做本地 OCR")
        excerpt = (text or "").strip()
        body = (
            "识图模式：只做本地 OCR，不调用 API。\n\n"
            "识别到的文字（已复制到剪贴板）：\n\n"
            + (excerpt or "（没有识别到文字）")
            + "\n\n回到题目页可以继续监测；按 F9 可立即重新识图。"
        )
        self._render(body, scroll_top=True)
        self._safe_show()

    def show_ocr_only(self, ocr_text: str):
        self.show_ocr_text(ocr_text)

    # ---- actions ---------------------------------------------------------------
    def _copy(self):
        if self._ocr_mode:
            if self.last_question:
                self._on_copy(self.last_question)
        elif self.last_answer:
            self._on_copy(self.last_answer)

    def _retry(self):
        self._on_retry()

    def _settings(self):
        self._on_settings()

    def hide(self):
        try:
            self.win.withdraw()
        except Exception:
            pass

    def toggle(self):
        if self.is_visible():
            self.hide()
        else:
            self._safe_show(force=True)

    def is_visible(self) -> bool:
        try:
            return self.win.state() != "withdrawn" and self.win.winfo_viewable()
        except Exception:
            return False

    def position(self) -> tuple[int, int]:
        try:
            return self.win.winfo_x(), self.win.winfo_y()
        except Exception:
            return 0, 0

    # ---- dragging --------------------------------------------------------------
    def _start_drag(self, event):
        self._drag = (event.x_root - self.win.winfo_x(), event.y_root - self.win.winfo_y())

    def _drag_move(self, event):
        if not self._drag:
            return
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        self.win.geometry(f"+{x}+{y}")

    def _end_drag(self, _event):
        self._drag = None
        if self._on_moved:
            self._on_moved(*self.position())

    def _on_configure(self, event):
        if event.widget is not self.win:
            return
        self._rounded_size = (event.width, event.height)

    def _on_wheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self.text.yview_scroll(delta * 3, "units")
        return "break"
