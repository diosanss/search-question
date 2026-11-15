# Changelog

## 1.0.6 — 2026-11-15

- Removed the screen flash during capture. The app now masks its own windows in the captured image instead of hiding them for 140 ms.
- Region selection now feeds the exact selected area to OCR; no automatic focus crop is applied on top of it.
- OCR-only mode suggests selecting a question region on first use and otherwise uses the same region as API mode.
- Filtered short symbol-only OCR noise such as `/ 皿丨司`.
- `config.example.json` documents the new OCR-mode prompt flag.

## 1.0.5 — 2026-11-15

- Added **OCR-only mode (识图模式)**: no API key, no network request, no model cost. It copies recognized question text to the clipboard and shows it in the overlay.
- Settings now has an OCR-only checkbox.
- `config.example.json` documents `behavior.ocr_only`.

## 1.0.4 — 2026-11-15

First public release.

- Windows local OCR (Windows.Media.Ocr), no cloud OCR.
- Automatic capture every 5 seconds, with change detection that ignores a blinking cursor but catches the next question.
- Answer overlay stays on top without stealing keyboard focus.
- OpenAI-compatible API support: DeepSeek, Qwen, GLM, Kimi, SiliconFlow, OpenAI, Ollama.
- Region capture, global hotkeys, DPAPI-encrypted API key storage.
- Fixed: next question was sometimes skipped because the whole-screen average diff was below the threshold.
- Fixed: a hotkey conflict could crash the hotkey thread.
- Fixed: a stale Win32 last-error could make the app think another instance was running.
- Fixed: settings/main windows are scaled down on short screens instead of clipping the footer.
- Removed the experimental web-version workflow.
