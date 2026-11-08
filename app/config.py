"""后台配置读写。

唯一持久化的数据就是 config.json（API Key、模型、自定义提示词）。
用户上传的原图和点评结果一律不落盘。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
CONFIG_PATH = DATA_DIR / "config.json"
_LOCK = threading.Lock()

PRESETS = {
    "qwen": {
        "label": "通义千问 VL（阿里云百炼）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
    },
    "glm": {
        "label": "智谱 GLM-4V",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-plus",
    },
    "doubao": {
        "label": "豆包视觉（火山方舟）",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-vision-pro-32k",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "ollama": {
        "label": "本机 Ollama（无需 Key）",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "qwen2.5vl:7b",
    },
    "custom": {
        "label": "自定义 OpenAI 兼容端点",
        "base_url": "",
        "model": "",
    },
}

DEFAULTS = {
    "provider": "qwen",
    "base_url": PRESETS["qwen"]["base_url"],
    "api_key": "",
    "model": PRESETS["qwen"]["model"],
    "temperature": 0.3,
    "max_tokens": 2500,
    "timeout": 90,
    "json_mode": True,
    "system_prompt": "",
}

CLEAR_KEY = "__CLEAR__"


def mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def _load_unlocked() -> dict:
    data = dict(DEFAULTS)
    try:
        if CONFIG_PATH.exists():
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return data


def get_config() -> dict:
    with _LOCK:
        return _load_unlocked()


def public_config() -> dict:
    """返回给后台页面的配置：API Key 只回显掩码，永不回传明文。"""
    cfg = get_config()
    view = {k: v for k, v in cfg.items() if k != "api_key"}
    view["api_key_masked"] = mask_key(cfg["api_key"])
    view["api_key_set"] = bool(cfg["api_key"])
    view["presets"] = PRESETS
    return view


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def save_config(patch: dict, default_prompt: str = "") -> dict:
    """校验并保存。api_key 留空表示不修改；传 CLEAR_KEY 表示清空。"""
    if not isinstance(patch, dict):
        raise ValueError("配置格式错误")
    with _LOCK:
        cfg = _load_unlocked()

        provider = str(patch.get("provider", cfg["provider"]))
        if provider not in PRESETS:
            raise ValueError("未知的服务商预设")
        cfg["provider"] = provider

        base_url = str(patch.get("base_url", cfg["base_url"])).strip().rstrip("/")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        cfg["base_url"] = base_url

        model = str(patch.get("model", cfg["model"])).strip()
        cfg["model"] = model

        key = patch.get("api_key", "")
        if key == CLEAR_KEY:
            cfg["api_key"] = ""
        elif isinstance(key, str) and key.strip() and key.strip() != mask_key(cfg["api_key"]):
            cfg["api_key"] = key.strip()

        try:
            temp = float(patch.get("temperature", cfg["temperature"]))
        except (TypeError, ValueError):
            temp = float(cfg["temperature"])
        cfg["temperature"] = round(max(0.0, min(1.0, temp)), 2)
        cfg["max_tokens"] = _clamp_int(patch.get("max_tokens", cfg["max_tokens"]), 500, 8000, 2500)
        cfg["timeout"] = _clamp_int(patch.get("timeout", cfg["timeout"]), 15, 300, 90)
        cfg["json_mode"] = bool(patch.get("json_mode", cfg["json_mode"]))

        prompt = patch.get("system_prompt", cfg["system_prompt"])
        prompt = prompt if isinstance(prompt, str) else ""
        cfg["system_prompt"] = "" if (default_prompt and prompt.strip() == default_prompt.strip()) else prompt

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass
        return dict(cfg)


def is_ready(cfg: dict) -> bool:
    """是否具备发起调用的条件。本机 Ollama 预设不需要 API Key。"""
    if not (cfg.get("base_url") and cfg.get("model")):
        return False
    if cfg.get("provider") == "ollama":
        return True
    return bool((cfg.get("api_key") or "").strip())
