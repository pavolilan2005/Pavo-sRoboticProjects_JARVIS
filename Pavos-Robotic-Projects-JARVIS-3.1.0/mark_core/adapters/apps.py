from __future__ import annotations

from typing import Any

from actions.browser_control import browser_control
from actions.open_app import open_app
from mark_core.models import ActionResult


class AppsAdapter:
    def __init__(self, registry, event_bus, ui=None):
        self.registry = registry
        self.event_bus = event_bus
        self.ui = ui

    def register(self) -> None:
        self.registry.register_handler("apps.open", "Abre una aplicación instalada.", self.open_app, tags=("apps",))
        self.registry.register_handler("browser.open", "Abre una URL en el navegador elegido.", self.open_browser, tags=("apps", "browser"))

    def open_app(self, params: dict[str, Any]) -> ActionResult:
        name = str(params.get("app_name") or params.get("name") or "").strip()
        if not name:
            return ActionResult.failure("Falta el nombre de la aplicación.")
        raw = open_app(parameters={"app_name": name}, response=None, player=self.ui)
        return ActionResult.success(str(raw or f"Abrí {name}."), app=name)

    def open_browser(self, params: dict[str, Any]) -> ActionResult:
        url = str(params.get("url", "")).strip()
        query = str(params.get("query", "")).strip()
        browser = str(params.get("browser", "")).strip()
        if not url and not query:
            return ActionResult.failure("Falta una URL o consulta.")
        payload = {"action": "go_to" if url else "search"}
        if url:
            payload["url"] = url
        if query:
            payload["query"] = query
        if browser:
            payload["browser"] = browser
        raw = browser_control(parameters=payload, player=self.ui)
        return ActionResult.success(str(raw or "Navegador preparado."), **payload)
