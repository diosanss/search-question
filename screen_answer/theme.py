"""Visual theme and DPI-aware sizing helpers."""

from __future__ import annotations

import tkinter as tk


FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Cascadia Mono"
EMOJI_FAMILY = "Segoe UI Symbol"

# A calm, dark blue palette that is easy on the eyes next to a browser.
BG = "#0B1220"
BG_SOFT = "#0E1728"
PANEL = "#111C2E"
CARD = "#142136"
CARD_HOVER = "#192A43"
BORDER = "#233451"
BORDER_SOFT = "#1A2940"
TEXT = "#E9F0FA"
TEXT_SOFT = "#C5D2E4"
MUTED = "#8EA2BC"
MUTED_DARK = "#647892"
ACCENT = "#38BDF8"
ACCENT_HOVER = "#5CCBFB"
ACCENT_DARK = "#0284C7"
ACCENT_TEXT = "#04121F"
GREEN = "#34D399"
GREEN_DARK = "#064E3B"
RED = "#F87171"
RED_DARK = "#7F1D1D"
AMBER = "#FBBF24"
AMBER_DARK = "#78350F"
WHITE = "#FFFFFF"


class Metrics:
    """Convert logical (96 DPI) design pixels to physical pixels.

    On short screens (e.g. 1366x768) the 820px-tall settings dialog would not
    fit. Shrink the whole UI proportionally instead of clipping the footer.
    """

    def __init__(self, root: tk.Misc):
        try:
            dpi_scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
        except Exception:
            dpi_scale = 1.0
        try:
            screen_height = int(root.winfo_screenheight())
        except Exception:
            screen_height = 1080
        designed_height = 860.0 * dpi_scale
        available = max(560.0, screen_height - 80.0)
        fit = min(1.0, available / designed_height)
        self.dpi_scale = dpi_scale
        self.scale = max(0.65, dpi_scale * fit)
        self.root = root

    def px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def font(self, size: float, weight: str = "normal", family: str = FONT_FAMILY):
        # Negative size = pixels, so the font follows the fitted UI scale too.
        pixels = max(9, int(round(size * (96.0 / 72.0) * self.scale)))
        return (family, -pixels, weight)

    def mono(self, size: float, weight: str = "normal"):
        return self.font(size, weight, MONO_FAMILY)


def configure_root(root: tk.Tk, metrics: Metrics) -> None:
    root.configure(bg=BG)
    root.option_add("*Font", metrics.font(9))
    root.option_add("*Background", BG)
    root.option_add("*Foreground", TEXT)
    root.option_add("*selectBackground", ACCENT_DARK)
    root.option_add("*selectForeground", WHITE)
    root.option_add("*Menu.background", PANEL)
    root.option_add("*Menu.foreground", TEXT)
    root.option_add("*Menu.activeBackground", CARD_HOVER)
    root.option_add("*Menu.activeForeground", WHITE)
    root.option_add("*Menu.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)
    root.option_add("*TCombobox*Listbox.selectForeground", WHITE)


def rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, **kwargs):
    """Draw a smooth-ish rounded rectangle on a Canvas."""
    r = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)
