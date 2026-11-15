# Security

## API keys

- API keys are stored locally, encrypted with Windows DPAPI, in `config.json`.
- `config.json` is in `.gitignore` and must never be committed.
- If a key is accidentally published, revoke it immediately in the provider console and create a new one.

## Screen data

- OCR runs locally with the Windows OCR engine.
- Screenshots are not written to disk by default.
- In vision mode, the cropped question image is sent to the model provider you configure.
- Logs do not contain OCR text or API keys.

## Reporting

Please do not publish a working API key, private conversation URL, or personal screen capture in an issue.
Report security problems privately to the repository owner, or open an issue with sensitive details removed.
