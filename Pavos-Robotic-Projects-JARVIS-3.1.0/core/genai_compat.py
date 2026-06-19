"""Compatibility layer for modules originally written for google.generativeai.

The project now depends only on the maintained ``google-genai`` SDK.  This
small adapter preserves the tiny subset of the old ``GenerativeModel`` API
used by the actions and agent modules, avoiding a risky rewrite of every
feature while removing the deprecated package and its startup warnings.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google import genai as _genai
from google.genai import types

_API_KEY: str | None = None


def _default_api_key() -> str:
    config = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
    try:
        value = json.loads(config.read_text(encoding="utf-8")).get("gemini_api_key", "")
    except Exception as exc:
        raise RuntimeError(f"No se pudo leer config/api_keys.json: {exc}") from exc
    value = str(value).strip()
    if not value:
        raise RuntimeError("Falta gemini_api_key en config/api_keys.json")
    return value


def configure(*, api_key: str | None = None, **_: Any) -> None:
    """Store the key, matching the old SDK's configure() call."""
    global _API_KEY
    if api_key:
        _API_KEY = str(api_key).strip()


def _convert_contents(contents: Any) -> Any:
    """Convert old inline-data dictionaries to google-genai Parts."""
    if not isinstance(contents, (list, tuple)):
        return contents

    converted: list[Any] = []
    for item in contents:
        if isinstance(item, dict) and "data" in item and "mime_type" in item:
            converted.append(
                types.Part.from_bytes(
                    data=bytes(item["data"]),
                    mime_type=str(item["mime_type"]),
                )
            )
        else:
            converted.append(item)
    return converted


class GenerativeModel:
    """Subset-compatible wrapper around Client.models.generate_content()."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        system_instruction: str | None = None,
        generation_config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name or kwargs.pop("model", None) or "gemini-2.5-flash"
        self.system_instruction = system_instruction
        self.generation_config = dict(generation_config or {})
        key = _API_KEY or _default_api_key()
        self._client = _genai.Client(api_key=key)

    def generate_content(
        self,
        contents: Any,
        *,
        generation_config: dict[str, Any] | None = None,
        **_: Any,
    ):
        config_values = dict(self.generation_config)
        config_values.update(generation_config or {})
        if self.system_instruction:
            config_values["system_instruction"] = self.system_instruction

        config = types.GenerateContentConfig(**config_values) if config_values else None
        return self._client.models.generate_content(
            model=self.model_name,
            contents=_convert_contents(contents),
            config=config,
        )
