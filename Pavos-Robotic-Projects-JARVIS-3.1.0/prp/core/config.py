from __future__ import annotations
import json
from pathlib import Path
from threading import RLock
from typing import Any

class ConfigStore:
    def __init__(self, root: Path):
        self.root = root
        self.config_dir = root / "config"
        self._lock = RLock()

    def path(self, name: str) -> Path:
        return self.config_dir / name

    def load(self, name: str, default: Any = None) -> Any:
        path = self.path(name)
        with self._lock:
            if not path.exists():
                return default
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return default

    def save(self, name: str, value: Any) -> None:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(path)

    def secrets(self) -> dict[str, Any]:
        data = self.load("secrets.json", {}) or {}
        return data if isinstance(data, dict) else {}
