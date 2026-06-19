from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class ConfigManager:
    """Thread-safe JSON configuration manager rooted at the project folder."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.config_dir = self.base_dir / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path(self, name: str) -> Path:
        return self.config_dir / name

    def load(self, name: str, default: Any = None) -> Any:
        path = self.path(name)
        with self._lock:
            if not path.exists():
                if default is not None:
                    self.save(name, default)
                    return json.loads(json.dumps(default, ensure_ascii=False))
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                if default is not None:
                    self.save(name, default)
                    return json.loads(json.dumps(default, ensure_ascii=False))
                raise

    def save(self, name: str, value: Any) -> None:
        path = self.path(name)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def update(self, name: str, mutator, default: Any = None) -> Any:
        with self._lock:
            value = self.load(name, default)
            result = mutator(value)
            final = value if result is None else result
            self.save(name, final)
            return final

    def api_key(self) -> str:
        data = self.load("api_keys.json", {}) or {}
        return str(data.get("gemini_api_key", "")).strip()

    def app(self) -> dict[str, Any]:
        return dict(self.load("app.json", {}) or {})
