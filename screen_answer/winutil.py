"""Thin ctypes helpers for window polish, DPI, and global hotkeys."""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:  # pragma: no cover
    dwmapi = None


def enable_dpi_awareness() -> bool:
    """Make Tk and mss use the same physical pixel coordinates."""
    try:
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [wintypes.HANDLE]
        fn.restype = wintypes.BOOL
        if fn(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return True
    except Exception as exc:
        log.debug("Per-monitor DPI awareness unavailable: %s", exc)
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_int
        return shcore.SetProcessDpiAwareness(2) == 0
    except Exception as exc:  # pragma: no cover
        log.debug("DPI awareness setup failed: %s", exc)
        return False


def set_app_user_model_id(app_id: str) -> None:
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:
        pass


def _dwm_set(hwnd: int, attr: int, value: int) -> bool:
    if dwmapi is None:
        return False
    try:
        data = ctypes.c_int(value)
        res = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), ctypes.c_int(attr), ctypes.byref(data), ctypes.sizeof(data)
        )
        return res == 0
    except Exception:
        return False


def apply_dark_titlebar(hwnd: int) -> None:
    # 20 on current Windows 11, 19 on older 1809+ builds.
    if not _dwm_set(hwnd, 20, 1):
        _dwm_set(hwnd, 19, 1)


def apply_rounded_corners(hwnd: int) -> None:
    _dwm_set(hwnd, 33, 2)  # DWMWCP_ROUND


def apply_round_region(hwnd: int, width: int, height: int, radius: int) -> None:
    """Clip an overrideredirect window to a rounded rectangle."""
    try:
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int
        region = gdi32.CreateRoundRectRgn(0, 0, int(width) + 1, int(height) + 1, int(radius), int(radius))
        if region:
            # On success Windows owns the region handle.
            if not user32.SetWindowRgn(wintypes.HWND(hwnd), region, True):
                gdi32.DeleteObject(region)
    except Exception as exc:
        log.debug("Rounded region failed: %s", exc)


def make_tool_window(hwnd: int) -> None:
    """Keep the overlay out of Alt-Tab and off the taskbar."""
    try:
        get_long = user32.GetWindowLongPtrW
        set_long = user32.SetWindowLongPtrW
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_long.restype = ctypes.c_ssize_t
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_NOACTIVATE = 0x08000000
        style = get_long(wintypes.HWND(hwnd), GWL_EXSTYLE)
        style = (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
        set_long(wintypes.HWND(hwnd), GWL_EXSTYLE, style)
    except Exception as exc:
        log.debug("Could not set tool-window style: %s", exc)


def show_no_activate(hwnd: int) -> None:
    try:
        user32.ShowWindow(wintypes.HWND(hwnd), 4)  # SW_SHOWNOACTIVATE
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            wintypes.HWND(-1),  # HWND_TOPMOST
            0, 0, 0, 0,
            0x0001 | 0x0002 | 0x0010,  # NOSIZE | NOMOVE | NOACTIVATE
        )
    except Exception:
        pass


def bring_topmost(hwnd: int, activate: bool = True) -> None:
    """Put a window in the topmost band without resizing or moving it."""
    try:
        flags = 0x0001 | 0x0002  # NOSIZE | NOMOVE
        if not activate:
            flags |= 0x0010  # NOACTIVATE
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, flags)
    except Exception:
        pass


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    try:
        rect = wintypes.RECT()
        if user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass
    return None


def rect_intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


class HotkeyManager(threading.Thread):
    """Registers F8/F9/F10 with a dedicated Win32 message loop."""

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_NOREPEAT = 0x4000

    def __init__(self, hotkeys: dict[int, tuple[int, Callable[[], None]]], on_error=None):
        super().__init__(name="screen-answer-hotkeys", daemon=True)
        self._hotkeys = hotkeys
        self._on_error = on_error
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self.failed: list[tuple[str, int]] = []

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        registered: list[int] = []
        for hotkey_id, (vk, callback) in self._hotkeys.items():
            if user32.RegisterHotKey(None, hotkey_id, self.MOD_NOREPEAT, vk):
                registered.append(hotkey_id)
            else:
                err = ctypes.get_last_error()
                self.failed.append((self._hotkey_label(hotkey_id), err))
                log.warning("Could not register hotkey %s (error %s)", self._hotkey_label(hotkey_id), err)
        self._ready.set()
        if self._on_error and self.failed:
            try:
                self._on_error(self.failed)
            except Exception:
                pass

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    item = self._hotkeys.get(int(msg.wParam))
                    if item:
                        try:
                            item[1]()
                        except Exception:
                            log.exception("Hotkey callback failed")
        finally:
            for hotkey_id in registered:
                try:
                    user32.UnregisterHotKey(None, hotkey_id)
                except Exception:
                    pass

    @staticmethod
    def _hotkey_label(hotkey_id: int) -> str:
        return {1: "F8", 2: "F9", 3: "F10"}.get(hotkey_id, str(hotkey_id))

    def stop(self) -> None:
        if self._thread_id:
            try:
                user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
            except Exception:
                pass
        if self.is_alive():
            self.join(timeout=1.0)


_single_mutex = None


def acquire_single_instance(name: str = "Local\\ScreenAnswer.SingleInstance") -> bool:
    """Return False when another copy is already running."""
    global _single_mutex
    try:
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        # CreateMutexW does not reliably clear the last error on success. A
        # stale 183 from an unrelated call would falsely report "already
        # running", so reset it explicitly.
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            return True
        if error == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _single_mutex = handle
        return True
    except Exception:
        return True
