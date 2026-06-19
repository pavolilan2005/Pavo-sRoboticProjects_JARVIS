from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

from prp.core.models import ActionResult


class AppsAdapter:
    def __init__(self, registry, event_bus, ui=None):
        self.registry = registry
        self.event_bus = event_bus
        self.ui = ui

    def register(self) -> None:
        r = self.registry.register_handler
        r("apps.open", "Abre una aplicación instalada.", self.open_app, tags=("apps", "pc"))
        r("browser.open", "Abre una URL en el navegador predeterminado.", self.open_url, tags=("browser", "pc"))

    def open_url(self, params: dict[str, Any]) -> ActionResult:
        url = str(params.get("url") or params.get("query") or "").strip()
        if not url:
            return ActionResult.failure("Falta la URL.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return ActionResult.success(f"Abrí {url}.", url=url)
        except Exception as exc:
            return ActionResult.failure(f"No pude abrir el navegador: {exc}", error=str(exc))

    def open_app(self, params: dict[str, Any]) -> ActionResult:
        name = str(params.get("app_name") or params.get("app") or "").strip()
        if not name:
            return ActionResult.failure("Falta el nombre de la aplicación.")
        try:
            path = self._resolve(name)
            if path:
                subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.startfile(name)  # type: ignore[attr-defined]
            self.event_bus.publish("apps.opened", {"name": name, "path": path or name}, "apps")
            return ActionResult.success(f"Abrí {name}.", app=name, path=path or name)
        except Exception as exc:
            return ActionResult.failure(f"No pude abrir {name}: {exc}", error=str(exc))

    @staticmethod
    def _resolve(name: str) -> str | None:
        direct = Path(name)
        if direct.exists():
            return str(direct)
        found = shutil.which(name)
        if found:
            return found
        key = name.lower().strip()
        candidates = {
            "obs": [r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"],
            "obs studio": [r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"],
            "spotify": [str(Path.home() / "AppData/Roaming/Spotify/Spotify.exe")],
            "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
            "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
            "visual studio code": [str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")],
            "vscode": [str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")],
            "bloc de notas": ["notepad.exe"],
            "notepad": ["notepad.exe"],
        }
        for candidate in candidates.get(key, []):
            if shutil.which(candidate) or Path(candidate).exists():
                return candidate
        return None
