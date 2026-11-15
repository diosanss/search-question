"""Model / capture settings dialog."""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Callable

from . import config as config_mod
from . import llm, theme, winutil
from .config import Config, PRESETS, PRESET_BY_NAME
from .theme import Metrics
from .widgets import CheckRow, HoverButton, LinkLabel

log = logging.getLogger(__name__)


def _top_hwnd(hwnd: int) -> int:
    try:
        user32 = __import__("ctypes").windll.user32
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


class SettingsDialog:
    def __init__(
        self,
        root: tk.Tk,
        cfg: Config,
        metrics: Metrics,
        on_saved: Callable[[], None],
        on_closed: Callable[[], None] | None = None,
        first_run: bool = False,
    ):
        self.root = root
        self.cfg = cfg
        self.m = metrics
        self.on_saved = on_saved
        self.on_closed = on_closed
        self.first_run = first_run
        self._test_queue: queue.Queue = queue.Queue()
        self._test_after = None
        self._key_visible = False
        self._closed = False

        self.win = tk.Toplevel(root)
        self.win.title("模型设置 · 屏幕解答")
        self.win.configure(bg=theme.BG)
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        w, h = metrics.px(640), metrics.px(860)
        self.win.geometry(f"{w}x{h}")
        self._center(w, h)
        try:
            self.win.grab_set()
        except Exception:
            pass
        self.win.bind("<Escape>", lambda _e: self._cancel())

        self.provider_var = tk.StringVar(value=cfg.provider)
        self.base_var = tk.StringVar(value=str(cfg.api.get("base_url", "")))
        self.model_var = tk.StringVar(value=str(cfg.api.get("model", "")))
        self.key_var = tk.StringVar(value=cfg.get_api_key())
        self.vision_var = tk.BooleanVar(value=bool(cfg.api.get("vision", False)))
        self.automin_var = tk.BooleanVar(value=bool(cfg.behavior.get("auto_minimize", False)))
        self.ocr_only_var = tk.BooleanVar(value=cfg.ocr_only)

        self._configure_ttk()
        self._build()
        self.win.after(80, self._init_window)

    def _center(self, w: int, h: int):
        try:
            self.win.update_idletasks()
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            rw, rh = self.root.winfo_width(), self.root.winfo_height()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            x = rx + (rw - w) // 2
            y = ry + (rh - h) // 2
            x = max(0, min(sw - w, x))
            y = max(0, min(sh - h, y))
            self.win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.win.geometry(f"{w}x{h}")

    def _init_window(self):
        try:
            self.win.update_idletasks()
            hwnd = _top_hwnd(self.win.winfo_id())
            winutil.apply_dark_titlebar(hwnd)
            winutil.apply_rounded_corners(hwnd)
            self.win.lift()
        except Exception:
            pass

    def _configure_ttk(self):
        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Settings.TCombobox",
            fieldbackground="#0A1526",
            background="#0A1526",
            foreground=theme.TEXT,
            arrowcolor=theme.MUTED,
            bordercolor=theme.BORDER,
            lightcolor=theme.BORDER,
            darkcolor=theme.BORDER,
            insertcolor=theme.TEXT,
            padding=self.m.px(7),
            font=self.m.font(10),
        )
        style.map(
            "Settings.TCombobox",
            fieldbackground=[("readonly", "#0A1526"), ("disabled", theme.CARD)],
            foreground=[("readonly", theme.TEXT), ("disabled", theme.MUTED)],
            selectbackground=[("readonly", "#0A1526")],
            selectforeground=[("readonly", theme.TEXT)],
        )
        self.win.option_add("*TCombobox*Listbox.background", theme.PANEL)
        self.win.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
        self.win.option_add("*TCombobox*Listbox.selectBackground", theme.ACCENT_DARK)
        self.win.option_add("*TCombobox*Listbox.selectForeground", theme.WHITE)
        self.win.option_add("*TCombobox*Listbox.font", self.m.font(10))

    def _build(self):
        m = self.m
        outer = tk.Frame(self.win, bg=theme.BG)
        outer.pack(fill="both", expand=True, padx=m.px(26), pady=m.px(20))

        header = tk.Frame(outer, bg=theme.BG)
        header.pack(fill="x")
        left = tk.Frame(header, bg=theme.BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(
            left, text="模型设置", bg=theme.BG, fg=theme.TEXT, font=m.font(17, "bold"), anchor="w"
        ).pack(fill="x")
        subtitle = "填入任意 OpenAI 兼容接口即可；配置只保存在本机。"
        if self.first_run:
            subtitle = "第一次使用：选一个服务商，填入 API Key，保存后就能自动解答。"
        tk.Label(
            left, text=subtitle, bg=theme.BG, fg=theme.MUTED, font=m.font(9), anchor="w", justify="left"
        ).pack(fill="x", pady=(m.px(4), 0))
        close = tk.Label(
            header, text="×", bg=theme.BG, fg=theme.MUTED, font=m.font(16), cursor="hand2", padx=m.px(6)
        )
        close.pack(side="right", anchor="n")
        close.bind("<Button-1>", lambda _e: self._cancel())
        close.bind("<Enter>", lambda _e: close.configure(fg=theme.TEXT))
        close.bind("<Leave>", lambda _e: close.configure(fg=theme.MUTED))

        tk.Frame(outer, bg=theme.BORDER_SOFT, height=1).pack(fill="x", pady=(m.px(14), m.px(14)))

        form = tk.Frame(outer, bg=theme.BG)
        form.pack(fill="both", expand=True)

        # Provider
        provider_box = self._field(form, "服务商")
        self.provider_combo = ttk.Combobox(
            provider_box,
            textvariable=self.provider_var,
            values=[p["name"] for p in PRESETS],
            state="readonly",
            style="Settings.TCombobox",
            font=m.font(10),
        )
        self.provider_combo.pack(fill="x", pady=(m.px(4), 0))
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)
        self.provider_hint = tk.Label(
            form,
            text="",
            bg=theme.BG,
            fg=theme.MUTED_DARK,
            font=m.font(8.5),
            anchor="w",
            justify="left",
            wraplength=m.px(560),
        )
        self.provider_hint.pack(fill="x", pady=(m.px(4), m.px(9)))

        # Base URL
        url_box = self._field(form, "API 地址")
        self.base_entry = self._entry(url_box, self.base_var)
        self.base_entry.pack(fill="x", pady=(m.px(4), 0))

        # Model
        model_box = self._field(form, "模型名称")
        self.model_entry = self._entry(model_box, self.model_var)
        self.model_entry.pack(fill="x", pady=(m.px(4), 0))

        # API Key
        key_box = self._field(form, "API Key")
        key_row = tk.Frame(key_box, bg=theme.BG)
        key_row.pack(fill="x", pady=(m.px(4), 0))
        self.key_entry = self._entry(key_row, self.key_var, show="•")
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.key_toggle = HoverButton(
            key_row,
            m,
            "显示",
            self._toggle_key,
            bg=theme.CARD,
            fg=theme.MUTED,
            font_size=8.5,
            padx=9,
            pady=8,
        )
        self.key_toggle.pack(side="left", padx=(m.px(6), 0))
        self.key_link = LinkLabel(key_box, m, "获取 API Key →", self._open_key_url, bg=theme.BG, font_size=8.5)
        self.key_link.pack(side="right", pady=(m.px(5), 0))
        self.key_note = tk.Label(
            form,
            text="Key 用 Windows DPAPI 加密后只保存在本机 config.json。",
            bg=theme.BG,
            fg=theme.MUTED_DARK,
            font=m.font(8),
            anchor="w",
        )
        self.key_note.pack(fill="x", pady=(m.px(3), m.px(8)))

        # Options
        self.vision_check = CheckRow(
            form,
            m,
            "把题目截图一起发给模型（视觉模型）",
            self.vision_var,
            bg=theme.BG,
        )
        self.vision_check.pack(fill="x")
        self.ocr_only_check = CheckRow(
            form,
            m,
            "识图模式（只 OCR 并复制文字，不调用 API）",
            self.ocr_only_var,
            bg=theme.BG,
        )
        self.ocr_only_check.pack(fill="x")
        self.ocr_only_note = tk.Label(
            form,
            text="不需要 API Key；识别到新文字会自动复制到剪贴板，不会请求模型。",
            bg=theme.BG,
            fg=theme.MUTED_DARK,
            font=m.font(8),
            anchor="w",
            justify="left",
            wraplength=m.px(540),
        )
        self.ocr_only_note.pack(fill="x", padx=(m.px(25), 0), pady=(m.px(1), m.px(6)))
        self.automin_check = CheckRow(
            form,
            m,
            "开始监测后自动最小化主窗口",
            self.automin_var,
            bg=theme.BG,
        )
        self.automin_check.pack(fill="x", pady=(m.px(3), m.px(8)))

        # Prompt
        prompt_header = tk.Frame(form, bg=theme.BG)
        prompt_header.pack(fill="x")
        tk.Label(
            prompt_header, text="答题提示词", bg=theme.BG, fg=theme.MUTED, font=m.font(8.5), anchor="w"
        ).pack(side="left")
        LinkLabel(
            prompt_header, m, "恢复默认", self._reset_prompt, bg=theme.BG, font_size=8
        ).pack(side="right")
        self.prompt_text = tk.Text(
            form,
            height=5,
            wrap="word",
            bg="#0A1526",
            fg=theme.TEXT_SOFT,
            insertbackground=theme.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT,
            font=m.font(9),
            padx=m.px(9),
            pady=m.px(7),
            spacing1=1,
            spacing3=2,
        )
        self.prompt_text.pack(fill="both", expand=True, pady=(m.px(4), m.px(6)))
        self.prompt_text.insert("1.0", str(self.cfg.data.get("prompt") or config_mod.SYSTEM_PROMPT))

        self.status_label = tk.Label(
            form,
            text="",
            bg=theme.BG,
            fg=theme.MUTED,
            font=m.font(8.5),
            anchor="w",
            justify="left",
            wraplength=m.px(350),
        )
        self.status_label.pack(fill="x", pady=(m.px(2), 0))

        footer = tk.Frame(outer, bg=theme.BG)
        footer.pack(fill="x", pady=(m.px(12), 0))
        self.save_btn = HoverButton(
            footer,
            m,
            "保存并关闭",
            self._save,
            bg=theme.ACCENT,
            fg=theme.ACCENT_TEXT,
            hover_bg=theme.ACCENT_HOVER,
            font_size=10,
            bold=True,
            padx=18,
            pady=10,
        )
        self.save_btn.pack(side="right")
        self.cancel_btn = HoverButton(
            footer,
            m,
            "取消",
            self._cancel,
            bg=theme.BG,
            fg=theme.MUTED,
            hover_bg=theme.CARD,
            font_size=9,
            padx=12,
            pady=10,
        )
        self.cancel_btn.pack(side="right", padx=(0, m.px(4)))
        self.test_btn = HoverButton(
            footer,
            m,
            "测试连接",
            self._test,
            bg=theme.CARD,
            fg=theme.TEXT_SOFT,
            hover_bg=theme.CARD_HOVER,
            font_size=9,
            padx=13,
            pady=10,
        )
        self.test_btn.pack(side="right", padx=(0, m.px(8)))

        self._update_provider_hint(self.provider_var.get())
        self._update_key_link()

    def _field(self, parent, label: str) -> tk.Frame:
        box = tk.Frame(parent, bg=theme.BG)
        box.pack(fill="x", pady=(0, self.m.px(7)))
        tk.Label(
            box, text=label, bg=theme.BG, fg=theme.MUTED, font=self.m.font(8.5), anchor="w"
        ).pack(fill="x")
        return box

    def _entry(self, parent, variable: tk.StringVar, show: str | None = None) -> tk.Entry:
        entry = tk.Entry(
            parent,
            textvariable=variable,
            bg="#0A1526",
            fg=theme.TEXT,
            insertbackground=theme.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT,
            font=self.m.font(10),
            exportselection=False,
        )
        if show:
            entry.configure(show=show)
        return entry

    # ---- provider helpers ------------------------------------------------------
    def _on_provider_change(self, _event=None):
        name = self.provider_var.get()
        preset = PRESET_BY_NAME.get(name)
        if preset:
            self.base_var.set(preset["base_url"])
            self.model_var.set(preset["model"])
            self.vision_var.set(bool(preset["vision"]))
        self._update_provider_hint(name)
        self._update_key_link()
        self._set_status("", theme.MUTED)

    def _update_provider_hint(self, name: str):
        preset = PRESET_BY_NAME.get(name)
        self.provider_hint.configure(text=(preset or {}).get("hint", ""))

    def _update_key_link(self):
        preset = PRESET_BY_NAME.get(self.provider_var.get()) or {}
        url = preset.get("key_url") or ""
        if url:
            self.key_link.configure(text="获取 API Key →", fg=theme.ACCENT)
            self._key_url = url
            self.key_link.pack(side="right", pady=(self.m.px(5), 0))
        else:
            self._key_url = ""
            self.key_link.pack_forget()

    def _open_key_url(self):
        url = getattr(self, "_key_url", "")
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def _toggle_key(self):
        self._key_visible = not self._key_visible
        self.key_entry.configure(show="" if self._key_visible else "•")
        self.key_toggle.set_text("隐藏" if self._key_visible else "显示")

    def _reset_prompt(self):
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", config_mod.SYSTEM_PROMPT)

    def _set_status(self, text: str, color: str):
        self.status_label.configure(text=text, fg=color)

    # ---- actions ---------------------------------------------------------------
    def _validate(self) -> bool:
        base = self.base_var.get().strip()
        model = self.model_var.get().strip()
        if not base.startswith(("http://", "https://")):
            self._set_status("API 地址要以 http:// 或 https:// 开头", theme.RED)
            return False
        if not model:
            self._set_status("请填写模型名称", theme.RED)
            return False
        return True

    def _test(self):
        if not self._validate():
            return
        self.test_btn.configure(state="disabled", text="测试中…")
        self._set_status("正在连接模型服务…", theme.MUTED)
        base = self.base_var.get().strip()
        model = self.model_var.get().strip()
        key = self.key_var.get().strip()
        timeout = int(self.cfg.api.get("timeout", 60))

        def worker():
            started = time.monotonic()
            try:
                text = llm.test_connection(base, model, key, timeout=min(30, timeout))
                self._test_queue.put((True, text, time.monotonic() - started))
            except Exception as exc:
                self._test_queue.put((False, str(exc), time.monotonic() - started))

        threading.Thread(target=worker, name="settings-test", daemon=True).start()
        self._poll_test()

    def _poll_test(self):
        if self._closed:
            return
        try:
            ok, message, elapsed = self._test_queue.get_nowait()
        except queue.Empty:
            self._test_after = self.win.after(120, self._poll_test)
            return
        self.test_btn.configure(state="normal", text="测试连接")
        if ok:
            self._set_status(f"连接成功：{message[:80]}（{elapsed:.1f}s）", theme.GREEN)
        else:
            self._set_status(message, theme.RED)

    def _save(self):
        if not self._validate():
            return
        preset = PRESET_BY_NAME.get(self.provider_var.get())
        self.cfg.api["provider"] = self.provider_var.get()
        self.cfg.api["base_url"] = self.base_var.get().strip().rstrip("/")
        self.cfg.api["model"] = self.model_var.get().strip()
        self.cfg.api["vision"] = bool(self.vision_var.get())
        self.cfg.set_api_key(self.key_var.get().strip())
        self.cfg.behavior["auto_minimize"] = bool(self.automin_var.get())
        self.cfg.behavior["ocr_only"] = bool(self.ocr_only_var.get())
        prompt = self.prompt_text.get("1.0", "end").strip()
        self.cfg.data["prompt"] = prompt or config_mod.SYSTEM_PROMPT
        try:
            self.cfg.save()
        except Exception as exc:
            self._set_status(f"保存失败：{exc}", theme.RED)
            return
        if preset and self.cfg.needs_key and not self.cfg.get_api_key():
            self._set_status("已保存，但还没填 API Key；自动解答暂时不可用。", theme.AMBER)
        try:
            self.on_saved()
        except Exception:
            log.exception("Settings saved callback failed")
        self._close()

    def _cancel(self):
        self._close()

    def _close(self):
        if self._closed:
            return
        self._closed = True
        if self._test_after:
            try:
                self.win.after_cancel(self._test_after)
            except Exception:
                pass
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_closed:
            try:
                self.on_closed()
            except Exception:
                pass
