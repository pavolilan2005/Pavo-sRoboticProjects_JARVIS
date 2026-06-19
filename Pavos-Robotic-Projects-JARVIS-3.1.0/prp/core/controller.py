from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any, Callable
from .capabilities import CapabilityRegistry
from .config import ConfigStore
from .events import EventBus
from .modes import ModeEngine
from .models import ActionResult, Capability, Risk
from .routines import RoutineEngine
from .automations import AutomationEngine
from prp.services.obs_service import ObsService
from prp.services.pc_service import PcService
from prp.services.serial_service import SerialService
from prp.services.spotify_service import SpotifyService
from prp.services.task_service import TaskService
from prp.services.notification_service import NotificationService
from prp.services.gmail_service import GmailService

class PrpController:
    def __init__(self, root: Path, log: Callable[[str], None]):
        self.root = root
        self.log = log
        self.config = ConfigStore(root)
        self.events = EventBus()
        self.capabilities = CapabilityRegistry()
        self.pc = PcService()
        self.spotify = SpotifyService(self.config)
        self.obs = ObsService(self.config)
        self.tasks = TaskService(self.config)
        self.notifications = NotificationService()
        self.gmail = GmailService(self.config)
        self.serial = SerialService(self.config, self._serial_event)
        self.routines = RoutineEngine(self.config, self.capabilities, self.events)
        self.modes = ModeEngine(self.config, self.routines, self.events)
        self._register()
        self.automations = AutomationEngine(self.config, self.capabilities, self.events)

    def _serial_event(self, message: dict[str, Any]) -> None:
        self.log(f"ESP32 {message.get('node_id')}: {message}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.events.publish("device.event", **message))
        except RuntimeError:
            pass

    def _register(self) -> None:
        add = self.capabilities.register
        add(Capability("app.open", "Abrir aplicación", self.pc.open_app))
        add(Capability("browser.open", "Abrir URL", self.pc.open_url))
        add(Capability("pc.status", "Estado de la computadora", self.pc.status))
        add(Capability("wait.seconds", "Esperar", self._wait))
        add(Capability("obs.status", "Estado de OBS", self.obs.status))
        add(Capability("obs.scene", "Cambiar escena de OBS", self.obs.scene))
        add(Capability("obs.record.start", "Iniciar grabación", self.obs.record_start, Risk.MEDIUM, True))
        add(Capability("obs.record.stop", "Detener grabación", self.obs.record_stop))
        add(Capability("spotify.status", "Estado de Spotify", self.spotify.status))
        add(Capability("spotify.play", "Reproducir en Spotify", self.spotify.play))
        add(Capability("spotify.play_alias", "Reproducir alias de Spotify", self.spotify.play_alias))
        add(Capability("spotify.pause", "Pausar Spotify", self.spotify.pause))
        add(Capability("spotify.volume", "Cambiar volumen de Spotify", self.spotify.volume))
        add(Capability("device.control", "Controlar dispositivo ESP32", self.serial.control_device))
        add(Capability("node.sync", "Sincronizar configuración ESP32", self.serial.sync_node, Risk.MEDIUM, True))
        add(Capability("scene.activate", "Activar escena domótica", self.activate_scene))
        add(Capability("routine.run", "Ejecutar rutina", self.routines.run))
        add(Capability("mode.start", "Activar modo", self.modes.start))
        add(Capability("mode.stop", "Desactivar modo", self.modes.stop))
        add(Capability("task.add", "Crear tarea", self.tasks.add))
        add(Capability("task.list", "Listar tareas", self.tasks.list))
        add(Capability("task.complete", "Completar tarea", self.tasks.complete))
        add(Capability("notification.show", "Mostrar notificación", self.notifications.show))
        add(Capability("gmail.unread", "Consultar correos no leídos", self.gmail.unread))

    async def _wait(self, seconds: float = 1.0) -> ActionResult:
        await asyncio.sleep(max(0.0, float(seconds)))
        return ActionResult.success("Espera completada")

    async def activate_scene(self, scene_id: str) -> ActionResult:
        scenes = (self.config.load("scenes.json", {}) or {}).get("scenes", [])
        scene = next((s for s in scenes if s.get("id") == scene_id), None)
        if not scene:
            return ActionResult.failure(f"Escena no encontrada: {scene_id}")
        failures = []
        for device_id, spec in scene.get("devices", {}).items():
            if isinstance(spec, dict):
                result = await asyncio.to_thread(self.serial.control_device, device_id, spec.get("action", "on"), spec.get("value"))
            else:
                result = await asyncio.to_thread(self.serial.control_device, device_id, str(spec), None)
            if not result.ok: failures.append(result.message)
        if failures: return ActionResult.failure("Escena aplicada parcialmente", "; ".join(failures))
        return ActionResult.success(f"Escena activada: {scene.get('name', scene_id)}")

    async def execute(self, name: str, args: dict[str, Any] | None = None) -> ActionResult:
        result = await self.capabilities.execute(name, args)
        self.log(f"{name}: {result.message}" + (f" | {result.error}" if result.error else ""))
        return result

    def close(self) -> None:
        self.serial.close()
