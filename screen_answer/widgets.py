"""Small Tk widgets used by the app."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from . import theme
from .theme import Metrics


class Card(tk.Frame):
    def __init__(self, master, metrics: Metrics, padding: int = 14, **kwargs):
        bg = kwargs.pop("bg", theme.CARD)
        super().__init__(
            master,
            bg=bg,
            highlightthickness=1,
            highlightbackground=kwargs.pop("border", theme.BORDER_SOFT),
            highlightcolor=kwargs.pop("border", theme.BORDER_SOFT),
            bd=0,
            **kwargs,
        )
        self.metrics = metrics
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=metrics.px(padding), pady=metrics.px(padding))


class HoverButton(tk.Button):
    """Flat button with a hover state and a subtle pressed state."""

    def __init__(
        self,
        master,
        metrics: Metrics,
        text: str = "",
        command: Callable | None = None,
        *,
        bg: str = theme.CARD,
        fg: str = theme.TEXT,
        hover_bg: str | None = None,
        active_bg: str | None = None,
        font_size: float = 9,
        bold: bool = False,
        padx: int = 12,
        pady: int = 8,
        anchor: str = "center",
        cursor: str = "hand2",
        **kwargs,
    ):
        self._normal_bg = bg
        self._hover_bg = hover_bg or theme.CARD_HOVER
        self._active_bg = active_bg or self._hover_bg
        self._enabled = True
        super().__init__(
            master,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=self._active_bg,
            activeforeground=fg,
            disabledforeground=theme.MUTED_DARK,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=metrics.font(font_size, "bold" if bold else "normal"),
            padx=metrics.px(padx),
            pady=metrics.px(pady),
            anchor=anchor,
            cursor=cursor,
            takefocus=True,
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")

    def _on_enter(self, _event=None):
        if self._enabled and str(self["state"]) != "disabled":
            self.configure(bg=self._hover_bg)

    def _on_leave(self, _event=None):
        if self._enabled:
            self.configure(bg=self._normal_bg)

    def _on_press(self, _event=None):
        if self._enabled and str(self["state"]) != "disabled":
            self.configure(bg=self._active_bg)

    def _on_release(self, _event=None):
        if self._enabled:
            x, y = self.winfo_pointerxy()
            inside = (
                self.winfo_rootx() <= x <= self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= y <= self.winfo_rooty() + self.winfo_height()
            )
            self.configure(bg=self._hover_bg if inside else self._normal_bg)

    def set_text(self, text: str):
        self.configure(text=text)

    def set_colors(self, bg: str, fg: str, hover_bg: str | None = None, active_bg: str | None = None):
        self._normal_bg = bg
        self._hover_bg = hover_bg or bg
        self._active_bg = active_bg or self._hover_bg
        self.configure(
            bg=bg,
            fg=fg,
            activebackground=self._active_bg,
            activeforeground=fg,
        )

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.configure(state="normal" if enabled else "disabled", cursor="hand2" if enabled else "arrow")
        if enabled:
            self.configure(bg=self._normal_bg)
        else:
            self.configure(bg=self._normal_bg)


class LinkLabel(tk.Label):
    def __init__(self, master, metrics: Metrics, text: str, command, **kwargs):
        super().__init__(
            master,
            text=text,
            bg=kwargs.pop("bg", theme.CARD),
            fg=kwargs.pop("fg", theme.ACCENT),
            font=metrics.font(kwargs.pop("font_size", 9)),
            cursor="hand2",
            bd=0,
            padx=0,
            pady=0,
            **kwargs,
        )
        self._command = command
        self.bind("<Button-1>", lambda _e: self._command())
        self.bind("<Enter>", lambda _e: self.configure(fg=theme.ACCENT_HOVER))
        self.bind("<Leave>", lambda _e: self.configure(fg=theme.ACCENT))


class Dot(tk.Canvas):
    def __init__(self, master, metrics: Metrics, color: str, size: int = 10, bg: str = theme.CARD):
        s = metrics.px(size)
        super().__init__(master, width=s, height=s, bg=bg, highlightthickness=0, bd=0)
        self._diameter = s
        self._dot = self.create_oval(1, 1, s - 1, s - 1, fill=color, outline="")

    def set_color(self, color: str):
        self.itemconfigure(self._dot, fill=color)


class Segmented(tk.Frame):
    """Two mutually exclusive pill buttons."""

    def __init__(
        self,
        master,
        metrics: Metrics,
        options: list[tuple[str, str]],
        command: Callable[[str], None],
        *,
        bg: str = theme.CARD,
        selected: str | None = None,
    ):
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.metrics = metrics
        self._command = command
        self._buttons: dict[str, tk.Button] = {}
        self._value = selected or options[0][0]
        self._bg = bg
        for value, label in options:
            b = tk.Button(
                self,
                text=label,
                command=lambda v=value: self.set(v, notify=True),
                bg=bg,
                fg=theme.MUTED,
                activebackground=theme.CARD_HOVER,
                activeforeground=theme.TEXT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=metrics.font(8.5),
                padx=metrics.px(10),
                pady=metrics.px(4),
                cursor="hand2",
            )
            b.pack(side="left", padx=(0, metrics.px(2)))
            self._buttons[value] = b
        self._refresh()

    @property
    def value(self) -> str:
        return self._value

    def set(self, value: str, notify: bool = False):
        if value not in self._buttons:
            return
        changed = value != self._value
        self._value = value
        self._refresh()
        if notify and changed:
            self._command(value)

    def _refresh(self):
        for value, button in self._buttons.items():
            if value == self._value:
                button.configure(
                    bg=theme.ACCENT_DARK,
                    fg=theme.WHITE,
                    activebackground=theme.ACCENT_DARK,
                    activeforeground=theme.WHITE,
                )
            else:
                button.configure(
                    bg=self._bg,
                    fg=theme.MUTED,
                    activebackground=theme.CARD_HOVER,
                    activeforeground=theme.TEXT,
                )


class CheckRow(tk.Frame):
    """A dark-theme checkbox that is visible on every Windows theme."""

    def __init__(
        self,
        master,
        metrics: Metrics,
        text: str,
        variable: tk.BooleanVar,
        *,
        bg: str = theme.BG,
        fg: str = theme.TEXT_SOFT,
    ):
        super().__init__(master, bg=bg, cursor="hand2")
        self.m = metrics
        self.var = variable
        self._bg = bg
        self._fg = fg
        self._box = tk.Canvas(self, width=metrics.px(17), height=metrics.px(17), bg=bg, bd=0, highlightthickness=0)
        self._box.pack(side="left", anchor="n", pady=(metrics.px(1), 0))
        self._label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=metrics.font(9),
            anchor="w",
            justify="left",
            wraplength=metrics.px(540),
        )
        self._label.pack(side="left", padx=(metrics.px(8), 0), fill="x", expand=True)
        for widget in (self, self._box, self._label):
            widget.bind("<Button-1>", self._toggle)
            widget.configure(cursor="hand2")
        self._trace = variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _event=None):
        self.var.set(not bool(self.var.get()))

    def _draw(self):
        c = self._box
        c.delete("all")
        s = self.m.px(17)
        checked = bool(self.var.get())
        c.create_rectangle(
            1, 1, s - 1, s - 1,
            fill=theme.ACCENT if checked else "#0A1526",
            outline=theme.ACCENT if checked else theme.BORDER,
            width=1,
        )
        if checked:
            c.create_line(
                s * 0.24, s * 0.52, s * 0.44, s * 0.71, s * 0.78, s * 0.30,
                fill=theme.ACCENT_TEXT, width=max(2, self.m.px(2)), capstyle="round", joinstyle="round",
            )


class Toast(tk.Frame):
    """A small transient message anchored inside a parent window."""

    def __init__(self, master, metrics: Metrics):
        super().__init__(
            master,
            bg=theme.CARD_HOVER,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            bd=0,
        )
        self.metrics = metrics
        self.label = tk.Label(
            self,
            text="",
            bg=theme.CARD_HOVER,
            fg=theme.TEXT,
            font=metrics.font(9),
            padx=metrics.px(12),
            pady=metrics.px(7),
        )
        self.label.pack()
        self._after_id = None

    def show(self, text: str, duration: int = 2200):
        self.label.configure(text=text)
        self.place(relx=0.5, rely=1.0, anchor="s", y=-self.metrics.px(18))
        self.lift()
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(duration, self.hide)

    def hide(self):
        self._after_id = None
        self.place_forget()
