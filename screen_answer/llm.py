"""OpenAI-compatible chat client with streaming and friendly errors."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Callable

import requests

from .config import Config

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMCancelled(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str


def chat_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise LLMError("还没有填写 API 地址")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "ScreenAnswer/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _error_from_response(response: requests.Response) -> str:
    status = response.status_code
    detail = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or err.get("code") or "")
            elif err:
                detail = str(err)
            elif data.get("message"):
                detail = str(data["message"])
    except Exception:
        try:
            detail = response.text[:400]
        except Exception:
            detail = ""
    detail = detail.strip().replace("\n", " ")
    if status == 401:
        msg = "API Key 无效或已过期，请到设置里重新填写"
    elif status == 403:
        msg = "没有权限调用这个模型（403），请检查 Key 和模型名"
    elif status == 404:
        msg = "接口地址或模型名不对（404），请检查 API 地址是否填到 /v1 这一级"
    elif status == 402:
        msg = "账户余额不足（402），请到模型服务商的开放平台充值"
    elif status == 429:
        msg = "请求太频繁或额度不足（429），稍后再试或检查账户余额"
    elif status >= 500:
        msg = f"模型服务暂时不可用（{status}）"
    else:
        msg = f"模型接口返回错误（{status}）"
    if detail:
        msg += f"：{detail[:220]}"
    return msg


def build_messages(cfg: Config, ocr_text: str, image_data_url: str | None) -> list[dict]:
    system = str(cfg.data.get("prompt") or "").strip()
    text = (ocr_text or "").strip()
    if len(text) > int(cfg.behavior.get("max_ocr_chars", 9000)):
        text = text[: int(cfg.behavior.get("max_ocr_chars", 9000))] + "\n……（后略）"
    parts: list[str] = []
    if text:
        parts.append("下面是从屏幕中识别到的题目文字（OCR 可能有少量错字）：")
        parts.append("<<<\n" + text + "\n>>>")
        if image_data_url:
            parts.append("同时附上题目区域的截图；若文字与截图冲突，以截图为准。")
        parts.append("请直接解答其中的题目。如果没有题目，只回复「未检测到题目」。")
    elif image_data_url:
        parts.append("请直接阅读截图中的题目并解答。如果没有题目，只回复「未检测到题目」。")
    else:
        parts.append("这次没有识别到文字，也没有截图，请提醒用户重新框选题目区域。")

    if image_data_url:
        content: list[dict] = [{"type": "text", "text": "\n".join(parts)}]
        content.append({"type": "image_url", "image_url": {"url": image_data_url}})
        user_content = content
    else:
        user_content = "\n".join(parts)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def _payload(cfg: Config, messages: list[dict], stream: bool, max_tokens: int) -> dict:
    api = cfg.api
    payload = {
        "model": api.get("model", ""),
        "messages": messages,
        "temperature": float(api.get("temperature", 0.2)),
        "max_tokens": max_tokens,
        "stream": stream,
    }
    # DeepSeek V4.1 Flash defaults to thinking mode. For a screen-answer
    # overlay we want the direct answer quickly, so disable thinking when the
    # request is going to DeepSeek.
    base = str(api.get("base_url", ""))
    if cfg.provider == "DeepSeek" or "api.deepseek.com" in base:
        payload["thinking"] = {"type": "disabled"}
    return payload


def _extract_delta(chunk: dict) -> str:
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    out.append(part["text"])
            return "".join(out)
    message = choice.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def stream_answer(
    cfg: Config,
    ocr_text: str,
    image_data_url: str | None,
    cancel_event: threading.Event,
    on_delta: Callable[[str], None],
) -> LLMResult:
    api = cfg.api
    url = chat_url(str(api.get("base_url", "")))
    key = cfg.get_api_key()
    model = str(api.get("model", "")).strip()
    if not model:
        raise LLMError("还没有填写模型名称，请到设置里选择或输入模型")
    messages = build_messages(cfg, ocr_text, image_data_url)
    payload = _payload(cfg, messages, True, 1100)
    timeout = (15, int(api.get("timeout", 60)))
    accumulated: list[str] = []

    try:
        with requests.post(
            url,
            headers=_headers(key),
            json=payload,
            stream=True,
            timeout=timeout,
            verify=True,
        ) as response:
            if response.status_code != 200:
                raise LLMError(_error_from_response(response))
            content_type = (response.headers.get("Content-Type") or "").lower()
            response.encoding = "utf-8"
            if "text/event-stream" not in content_type and "stream" not in content_type:
                # A few gateways ignore stream=true and return a single JSON body.
                data = response.json()
                if isinstance(data, dict) and data.get("error"):
                    raise LLMError(_error_from_response(response))
                text = _extract_delta(data)
                if not text:
                    choices = data.get("choices") or []
                    if choices:
                        text = ((choices[0] or {}).get("message") or {}).get("content") or ""
                if not isinstance(text, str) or not text.strip():
                    raise LLMError("模型没有返回内容，请稍后重试")
                accumulated.append(text)
                on_delta(text)
                return LLMResult(text.strip(), model)

            for raw_line in response.iter_lines(decode_unicode=True):
                if cancel_event.is_set():
                    raise LLMCancelled("已取消")
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    err = chunk["error"]
                    detail = err.get("message") if isinstance(err, dict) else str(err)
                    raise LLMError(f"模型返回错误：{detail}")
                piece = _extract_delta(chunk)
                if piece:
                    accumulated.append(piece)
                    on_delta("".join(accumulated))
            if cancel_event.is_set():
                raise LLMCancelled("已取消")
            text = "".join(accumulated).strip()
            if not text:
                raise LLMError("模型没有返回文字，可能被内容过滤了；换一个模型或稍后再试")
            return LLMResult(text, model)
    except LLMError:
        raise
    except LLMCancelled:
        raise
    except requests.exceptions.SSLError as exc:
        raise LLMError(f"SSL 连接失败，请检查网络或代理：{exc}") from exc
    except requests.exceptions.ProxyError as exc:
        raise LLMError(f"代理连接失败，请检查系统代理：{exc}") from exc
    except requests.exceptions.Timeout as exc:
        raise LLMError("模型响应超时，请稍后重试或调大超时时间") from exc
    except requests.exceptions.ConnectionError as exc:
        raise LLMError(f"连不上模型服务，请检查网络和 API 地址：{exc}") from exc
    except Exception as exc:
        log.exception("LLM request failed")
        raise LLMError(f"请求模型时出错：{exc}") from exc


def test_connection(
    base_url: str,
    model: str,
    api_key: str,
    timeout: int = 30,
) -> str:
    url = chat_url(base_url)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复：OK"}],
        "temperature": 0,
        "max_tokens": 8,
        "stream": False,
    }
    if "api.deepseek.com" in url:
        payload["thinking"] = {"type": "disabled"}
    try:
        response = requests.post(
            url,
            headers={**_headers(api_key), "Accept": "application/json"},
            json=payload,
            timeout=(10, timeout),
        )
        if response.status_code != 200:
            raise LLMError(_error_from_response(response))
        data = response.json()
        choices = data.get("choices") or []
        text = ""
        if choices:
            message = (choices[0] or {}).get("message") or {}
            text = str(message.get("content") or "").strip()
        return text or "连接成功（模型返回为空）"
    except LLMError:
        raise
    except requests.exceptions.Timeout as exc:
        raise LLMError("连接超时，请检查网络或地址") from exc
    except Exception as exc:
        raise LLMError(f"连接失败：{exc}") from exc
