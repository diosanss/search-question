# Contributing

Thanks for helping! This is a small Windows desktop app, so keep changes focused and easy to review.

## Before you start

- Windows 10/11
- Python 3.12 (recommended)
- Run `install.bat` once, then `run.bat`
- Run `run_tests.bat` before opening a pull request

## Good first issues

- Better OCR preprocessing for dark-mode pages
- Better question-region detection for multi-column pages
- More provider presets / error messages
- Accessibility and keyboard navigation improvements

## Pull requests

1. Fork the repo and create a branch.
2. Keep one logical change per pull request.
3. Add or update tests in `tests/` when changing core logic.
4. Update `README.md` / `CHANGELOG.md` for user-visible changes.
5. Never commit `config.json`, `logs/`, `.venv/`, or `dist/`.

## Bug reports

Please include:

- Windows version and display scaling (e.g. Windows 11 24H2, 150%)
- App version
- What you did, what happened, and what you expected
- `logs/app.log` with **API keys and personal screen text removed**
- A screenshot if it helps (blur any private information)

Do not open a public issue containing an API key or a private DeepSeek conversation link.
