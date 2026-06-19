from __future__ import annotations

import ctypes
import platform
from typing import Any

from prp.core.models import ActionResult


class MediaAdapter:
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    VK_MEDIA_STOP = 0xB2
    VK_MEDIA_PLAY_PAUSE = 0xB3
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF

    def __init__(self, registry, event_bus):
        self.registry = registry
        self.event_bus = event_bus

    def register(self) -> None:
        r = self.registry.register_handler
        r("media.play_pause", "Alterna reproducción y pausa multimedia.", lambda p: self._press(self.VK_MEDIA_PLAY_PAUSE, "Reproducción alternada."), tags=("media",))
        r("media.next", "Siguiente pista multimedia.", lambda p: self._press(self.VK_MEDIA_NEXT_TRACK, "Siguiente pista."), tags=("media",))
        r("media.previous", "Pista anterior multimedia.", lambda p: self._press(self.VK_MEDIA_PREV_TRACK, "Pista anterior."), tags=("media",))
        r("media.stop", "Detiene reproducción multimedia.", lambda p: self._press(self.VK_MEDIA_STOP, "Reproducción detenida."), tags=("media",))
        r("media.volume_up", "Sube volumen del sistema.", lambda p: self._press(self.VK_VOLUME_UP, "Volumen aumentado."), tags=("media", "pc"))
        r("media.volume_down", "Baja volumen del sistema.", lambda p: self._press(self.VK_VOLUME_DOWN, "Volumen reducido."), tags=("media", "pc"))
        r("media.mute", "Silencia o reactiva volumen del sistema.", lambda p: self._press(self.VK_VOLUME_MUTE, "Silencio alternado."), tags=("media", "pc"))

    def _press(self, vk: int, message: str) -> ActionResult:
        if platform.system() != "Windows":
            return ActionResult.failure("Las teclas multimedia de respaldo están implementadas para Windows.")
        try:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            self.event_bus.publish("media.key", {"vk": vk}, "media")
            return ActionResult.success(message)
        except Exception as exc:
            return ActionResult.failure(f"No pude enviar la tecla multimedia: {exc}", error=str(exc))
