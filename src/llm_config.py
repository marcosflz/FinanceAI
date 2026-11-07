import os
from typing import Optional

PROVIDER_PRESETS = {
    "openai": {"base_url": ""},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1"},
    "ollama": {"base_url": "http://localhost:11434/v1"},
    "lmstudio": {"base_url": "http://localhost:1234/v1"},
    "custom": {"base_url": ""},
}

_DEFAULT_MODEL = "gpt-4o-mini"


def resolve_llm_settings() -> dict:
    from .db.lookups import get_all_app_config

    cfg = get_all_app_config()
    api_key = (
        cfg.get("llm_api_key")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )
    base_url = cfg.get("llm_base_url") or os.getenv("LLM_BASE_URL") or ""
    model = cfg.get("llm_model") or os.getenv("LLM_MODEL") or _DEFAULT_MODEL
    provider = cfg.get("llm_provider") or ""
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "provider": provider,
    }


def mask_api_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
