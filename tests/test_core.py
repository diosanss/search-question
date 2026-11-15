"""Unit tests that do not need a real API key or the Windows OCR language pack."""

import tempfile
import unittest
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from screen_answer import capture, winutil
from screen_answer.config import Config
from screen_answer.llm import chat_url
from screen_answer.ocr_engine import clean_text, normalize_for_hash


def question_page(variant: int = 0) -> Image.Image:
    im = Image.new("RGB", (1600, 900), "white")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((120, 100, 1480, 800), radius=24, fill="white", outline="black", width=2)
    for i in range(4):
        y = 200 + i * 110
        d.rectangle((200, y, 1250, y + 36), fill="#222222")
        if variant:
            d.rectangle((260, y + 50, 1000, y + 70), fill="#777777")
        else:
            d.rectangle((260, y + 50, 900, y + 70), fill="#777777")
    return im


class ChangeDetectionTests(unittest.TestCase):
    def test_same_frame_is_unchanged(self):
        a = capture.thumb(question_page(0))
        b = capture.thumb(question_page(0))
        changed, metrics = capture.is_changed(a, b)
        self.assertFalse(changed)
        self.assertLess(metrics.mean, 0.01)

    def test_next_question_is_detected(self):
        changed, metrics = capture.is_changed(
            capture.thumb(question_page(0)),
            capture.thumb(question_page(1)),
        )
        self.assertTrue(changed)
        self.assertGreater(metrics.hard_ratio, 0.001)

    def test_blinking_cursor_does_not_trigger(self):
        a = question_page(0)
        b = a.copy()
        ImageDraw.Draw(b).rectangle((700, 400, 702, 430), fill="black")
        changed, metrics = capture.is_changed(capture.thumb(a), capture.thumb(b))
        self.assertFalse(changed)
        self.assertLess(metrics.hard_ratio, 0.001)

    def test_mask_uses_page_color_without_flash(self):
        image = question_page(0)
        masked = capture.mask_regions(image, [(120, 100, 300, 300)], (0, 0, image.width, image.height))
        # The overlay rectangle is filled with the page's median color, not a
        # black block that would confuse OCR.
        pixel = masked.getpixel((130, 110))
        self.assertGreater(pixel[0], 250)
        self.assertEqual(pixel[0], pixel[1])
        self.assertEqual(pixel[1], pixel[2])


class UrlTests(unittest.TestCase):
    def test_deepseek_base_url(self):
        self.assertEqual(
            chat_url("https://api.deepseek.com"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_v1_base_url(self):
        self.assertEqual(
            chat_url("https://api.openai.com/v1/"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_full_endpoint_is_not_duplicated(self):
        self.assertEqual(
            chat_url("https://example.com/v1/chat/completions"),
            "https://example.com/v1/chat/completions",
        )

    def test_empty_url_is_invalid(self):
        with self.assertRaises(Exception):
            chat_url("")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_and_clamping(self):
        cfg = Config(self.path)
        self.assertEqual(cfg.interval, 5)
        self.assertEqual(cfg.api["model"], "deepseek-flash")
        self.assertEqual(cfg.api["base_url"], "https://api.deepseek.com")
        self.assertFalse(cfg.ocr_only)
        cfg.capture["interval"] = 999
        cfg.save()
        self.assertEqual(Config(self.path).interval, 120)

    def test_ocr_only_roundtrip(self):
        cfg = Config(self.path)
        cfg.behavior["ocr_only"] = True
        cfg.save()
        self.assertTrue(Config(self.path).ocr_only)

    def test_old_web_fields_are_removed(self):
        cfg = Config(self.path)
        cfg.data["behavior"]["answer_mode"] = "web"
        cfg.data["behavior"]["web_answer_region"] = [1, 2, 3, 4]
        cfg.save()
        loaded = Config(self.path)
        self.assertNotIn("answer_mode", loaded.behavior)
        self.assertNotIn("web_answer_region", loaded.behavior)

    def test_malformed_sections_fall_back_to_defaults(self):
        self.path.write_text('{"api": "bad", "capture": [], "behavior": null}', encoding="utf-8")
        cfg = Config(self.path)
        self.assertIsInstance(cfg.api, dict)
        self.assertEqual(cfg.interval, 5)
        self.assertIsInstance(cfg.behavior, dict)

    def test_api_key_is_not_stored_as_plaintext(self):
        cfg = Config(self.path)
        cfg.set_api_key("sk-unit-test-secret")
        cfg.save()
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("sk-unit-test-secret", raw)
        self.assertEqual(Config(self.path).get_api_key(), "sk-unit-test-secret")


class TextTests(unittest.TestCase):
    def test_normalize_for_hash(self):
        self.assertEqual(
            normalize_for_hash("答案：A. 恶心、呕吐"),
            normalize_for_hash("答案 A 恶心 呕吐"),
        )

    def test_short_symbol_noise_is_removed(self):
        text = clean_text("A. 恶心、呕吐\n/ 皿丨司\nB. 脉搏加快")
        self.assertIn("A. 恶心、呕吐", text)
        self.assertIn("B. 脉搏加快", text)
        self.assertNotIn("皿丨司", text)


class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_is_rejected(self):
        name = "Local\\ScreenAnswer.Test." + uuid.uuid4().hex
        self.assertTrue(winutil.acquire_single_instance(name))
        self.assertFalse(winutil.acquire_single_instance(name))


if __name__ == "__main__":
    unittest.main()
