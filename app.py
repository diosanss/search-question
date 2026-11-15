"""Entry point for 屏幕解答 (Screen Answer)."""

from __future__ import annotations

import ctypes
import logging
import sys
import traceback

from screen_answer import winutil

# Must happen before Tk creates any window so Tk and mss agree on pixels.
winutil.enable_dpi_awareness()
winutil.set_app_user_model_id("ScreenAnswer.App.1")

log = logging.getLogger(__name__)


def _fatal(title: str, message: str):
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        print(message, file=sys.stderr)


def _selftest(argv: list[str]) -> int:
    """Headless smoke test used after packaging: capture -> OCR -> report."""
    import logging

    from screen_answer.config import LOG_DIR, setup_logging

    setup_logging(debug=False)
    log_path = LOG_DIR / "selftest.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    try:
        from PIL import Image

        from screen_answer import capture
        from screen_answer.ocr_engine import OcrService

        image_arg = None
        try:
            idx = argv.index("--selftest")
            if idx + 1 < len(argv) and not argv[idx + 1].startswith("--"):
                image_arg = argv[idx + 1]
        except ValueError:
            pass
        if image_arg:
            image = Image.open(image_arg)
            source = image_arg
        else:
            image = capture.grab()
            source = "current screen"
        result = OcrService().recognize(image)
        log.info("SELFTEST OK source=%s size=%s chars=%s focus=%s", source, image.size, len(result.text), result.focus_box)
        log.info("SELFTEST TEXT: %s", (result.focus_text or result.text)[:1200])
        return 0
    except Exception:
        log.exception("SELFTEST FAILED")
        return 1


def main() -> int:
    debug = "--debug" in sys.argv
    try:
        from screen_answer.config import Config, setup_logging

        setup_logging(debug=debug)
    except Exception:
        _fatal("屏幕解答 · 启动失败", "日志模块初始化失败：\n" + traceback.format_exc())
        return 1

    if "--selftest" in sys.argv:
        return _selftest(sys.argv)

    if not winutil.acquire_single_instance():
        _fatal("屏幕解答", "屏幕解答已经在运行了。\n\n请从任务栏打开它，或先关闭旧窗口。")
        return 0

    try:
        import tkinter as tk

        from screen_answer.main_ui import ScreenAnswerApp
    except Exception:
        _fatal(
            "屏幕解答 · 缺少依赖",
            "启动失败，依赖没有装好。\n\n"
            "请在程序目录运行「install.bat」，或执行：\n"
            "  .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n\n"
            + traceback.format_exc(),
        )
        return 1

    try:
        cfg = Config()
        root = tk.Tk()
        app = ScreenAnswerApp(root, cfg)
        if "--autostart" in sys.argv:
            root.after(700, app.start_monitor)
        log.info("Screen Answer started")
        root.mainloop()
        log.info("Screen Answer exited")
        return 0
    except Exception:
        log.exception("Unhandled startup error")
        _fatal("屏幕解答 · 启动失败", "程序遇到错误：\n\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
