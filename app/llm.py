"""与视觉大模型通信：OpenAI 兼容 /chat/completions，图片以 base64 内联。"""
from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from .parsing import FormatError, extract_json, flatten_content, validate_result


class ModelError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _headers(cfg: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    key = (cfg.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _payload(cfg: dict, messages: list[dict], max_tokens: int, json_mode: bool) -> dict:
    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": cfg["temperature"],
    }
    if json_mode and cfg.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
    return payload


def _image_block(jpeg: bytes) -> dict:
    b64 = base64.b64encode(jpeg).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


async def _post(cfg: dict, messages: list[dict], max_tokens: int, json_mode: bool = True) -> tuple[str, dict]:
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    timeout = httpx.Timeout(float(cfg["timeout"]))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=_headers(cfg), json=_payload(cfg, messages, max_tokens, json_mode))
    except httpx.TimeoutException as exc:
        raise ModelError(f"模型响应超时（{cfg['timeout']} 秒），可稍后重试") from exc
    except httpx.HTTPError as exc:
        raise ModelError("无法连接模型服务，请检查 Base URL 与 NAS 的网络出口") from exc

    if resp.status_code == 401 or resp.status_code == 403:
        raise ModelError("API Key 无效或没有权限，请到后台检查", 400)
    if resp.status_code == 429:
        raise ModelError("模型额度不足或触发限流，请稍后再试", 429)
    if resp.status_code >= 500:
        raise ModelError(f"模型服务暂时不可用（HTTP {resp.status_code}）", 502)
    if resp.status_code != 200:
        raise ModelError(f"模型返回异常（HTTP {resp.status_code}）：{resp.text[:160]}", 502)

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ModelError("模型返回结构异常，可能该端点不是 OpenAI 兼容格式") from exc

    text = flatten_content(content)
    if not text.strip():
        raise ModelError("模型没有返回内容")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return text, {"total_tokens": usage.get("total_tokens", 0)}


async def call_review(cfg: dict, system_prompt: str, jpeg: bytes, title: str) -> tuple[dict, list[str], dict]:
    """单次调用 + 一次兜底重试。返回 (结果, 警告, 用量)。"""
    title_text = title.strip() if isinstance(title, str) else ""
    user_text = (
        f"作品标题：{title_text}。请按 system 中的 JSON 契约输出。"
        if title_text
        else "用户未提供作品标题，title_analysis 必须为 null。请按 system 中的 JSON 契约输出。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": user_text},
            _image_block(jpeg),
        ]},
    ]

    last_error: Exception | None = None
    for attempt in range(2):
        attempt_cfg = dict(cfg)
        attempt_messages = messages
        if attempt == 1:
            attempt_cfg["temperature"] = 0.1
            attempt_messages = messages + [{
                "role": "user",
                "content": [{"type": "text", "text": "上一次输出不符合契约。请重新判断，只输出一个合法的 JSON 对象，亮点与问题各至少 3 条且每条都带画面证据。"}],
            }]
        try:
            text, usage = await _post(attempt_cfg, attempt_messages, int(cfg["max_tokens"]), True)
            obj = extract_json(text)
            result, warnings = validate_result(obj)
            return result, warnings, usage
        except FormatError as exc:
            last_error = exc
        except ModelError as exc:
            last_error = exc
            if exc.status not in (502, 429):
                raise

    raise ModelError(f"模型输出不符合要求，已重试一次仍未通过：{last_error}")


async def test_connection(cfg: dict, jpeg: bytes) -> dict:
    """发一张极小图做真实调用，只验证连通性与鉴权。"""
    test_cfg = dict(cfg)
    test_cfg["timeout"] = min(int(cfg["timeout"]), 30)
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "只回复两个字：正常"},
            _image_block(jpeg),
        ]},
    ]
    started = time.monotonic()
    text, _ = await _post(test_cfg, messages, 24, False)
    return {
        "ok": True,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "model": cfg["model"],
        "preview": text.strip()[:40],
    }
