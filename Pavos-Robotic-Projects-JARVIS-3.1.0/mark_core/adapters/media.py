from __future__ import annotations

from typing import Any

from mark_core.models import ActionResult


class MediaAdapter:
    """Generic media-key fallback that works without a service API."""

    def __init__(self, registry, event_bus):
        self.registry = registry
        self.event_bus = event_bus

    def register(self) -> None:
        for name, desc, action in [
            ("media.play_pause", "Alterna reproducción y pausa multimedia.", "playpause"),
            ("media.next", "Avanza a la siguiente pista.", "nexttrack"),
            ("media.previous", "Regresa a la pista anterior.", "prevtrack"),
            ("media.stop", "Detiene la reproducción multimedia.", "stop"),
        ]:
            self.registry.register_handler(name, desc, lambda _p, a=action: self._press(a), tags=("media",))
        self.registry.register_handler("media.volume", "Ajusta el volumen general mediante teclas multimedia.", self.volume, tags=("media", "pc"))

    def _press(self, key: str) -> ActionResult:
        try:
            import pyautogui
            pyautogui.press(key)
            return ActionResult.success("Control multimedia enviado.", key=key)
        except Exception as exc:
            return ActionResult.failure(f"No pude enviar la tecla multimedia: {exc}", error=str(exc))

    def volume(self, params: dict[str, Any]) -> ActionResult:
        action = str(params.get("action", "")).lower()
        amount = max(1, min(50, int(params.get("amount", 2))))
        if "volume" in params:
            try:
                from actions.computer_settings import computer_settings
                raw = computer_settings(
                    parameters={"action": "volume", "value": str(int(params["volume"])), "description": "set system volume"},
                    response=None,
                    player=None,
                )
                return ActionResult.success(str(raw or f"Volumen ajustado a {params['volume']} %."))
            except Exception as exc:
                return ActionResult.failure(f"No pude ajustar el volumen: {exc}")
        key = "volumeup" if action in {"up", "subir", "+"} else "volumedown"
        try:
            import pyautogui
            pyautogui.press(key, presses=amount, interval=0.03)
            return ActionResult.success(f"Volumen {'subido' if key == 'volumeup' else 'bajado'}.")
        except Exception as exc:
            return ActionResult.failure(f"No pude controlar el volumen: {exc}")
