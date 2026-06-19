from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .automations import AutomationEngine
from .capabilities import CapabilityRegistry
from .event_bus import EventBus
from .models import ActionResult
from .modes import ModeManager
from .routines import RoutineEngine
from .storage import JsonStore
from .adapters.apps import AppsAdapter
from .adapters.audio import AudioSettingsAdapter
from .adapters.esp32 import ESP32Adapter
from .adapters.gmail import GmailAdapter
from .adapters.media import MediaAdapter
from .adapters.notifications import NotificationsAdapter
from .adapters.obs import OBSAdapter
from .adapters.pc import PCAdapter
from .adapters.spotify import SpotifyAdapter


DEFAULT_INTEGRATIONS = {
    "version": 1,
    "obs": {"host": "localhost", "port": 4455, "password": "", "timeout": 5},
    "spotify": {
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "http://127.0.0.1:8888/callback",
        "preferred_device": "",
    },
    "gmail": {
        "credentials_path": "config/gmail_credentials.json",
        "token_path": "config/gmail_token.json",
    },
    "windows_notifications": {"enabled": False},
}


class PRPPlatform:
    """Central orchestration layer for PAVO'S ROBOTIC PROJECTS // JARVIS."""

    def __init__(
        self,
        base_dir: str | Path,
        ui=None,
    ):
        self.base_dir = Path(base_dir)
        self.ui = ui
        self.event_bus = EventBus()
        self.integrations_store = JsonStore(
            self.base_dir / "config" / "integrations.json", DEFAULT_INTEGRATIONS
        )
        self.registry = CapabilityRegistry(self.event_bus, confirmer=self._confirm)

        self.audio = AudioSettingsAdapter(self.base_dir)
        self.apps = AppsAdapter(self.registry, self.event_bus, ui)
        self.pc = PCAdapter(self.registry, self.event_bus, ui)
        self.media = MediaAdapter(self.registry, self.event_bus)
        self.notifications = NotificationsAdapter(self.registry, self.event_bus, ui)
        self.obs = OBSAdapter(self.registry, self.event_bus, self.get_integrations, ui)
        self.spotify = SpotifyAdapter(self.registry, self.event_bus, self.get_integrations, self.base_dir)
        self.gmail = GmailAdapter(self.registry, self.event_bus, self.get_integrations, self.base_dir)
        self.esp32 = ESP32Adapter(
            self.registry,
            self.event_bus,
            self.base_dir,
        )

        for adapter in (
            self.apps,
            self.pc,
            self.media,
            self.notifications,
            self.obs,
            self.spotify,
            self.gmail,
            self.esp32,
        ):
            adapter.register()

        self.routines = RoutineEngine(
            self.registry, self.event_bus, self.base_dir / "config" / "routines.json"
        )
        self.modes = ModeManager(
            self.routines,
            self.registry,
            self.event_bus,
            self.base_dir / "config" / "modes.json",
            self.base_dir / "config" / "mode_state.json",
        )
        self.automations = AutomationEngine(
            self.registry,
            self.routines,
            self.modes,
            self.event_bus,
            self.base_dir / "config" / "automations.json",
        )
        self._register_orchestration_capabilities()
        self.event_bus.subscribe("routine.*", self._log_event)
        self.event_bus.subscribe("mode.*", self._log_event)
        self.event_bus.subscribe("automation.finished", self._log_event)
        from .runtime import set_platform
        set_platform(self)

    def _register_orchestration_capabilities(self) -> None:
        r = self.registry.register_handler
        r("routine.run", "Ejecuta una rutina configurable por nombre.", self._cap_run_routine, tags=("orchestration", "routine"))
        r("routine.list", "Lista las rutinas configuradas.", self._cap_list_routines, tags=("orchestration", "routine"))
        r("mode.manage", "Activa, desactiva o consulta modos persistentes.", self._cap_manage_mode, tags=("orchestration", "mode"))
        r("automation.list", "Lista automatizaciones configuradas.", self._cap_list_automations, tags=("orchestration", "automation"))
        r("system.capabilities", "Lista todas las capacidades registradas en JARVIS.", self._cap_list_capabilities, tags=("orchestration", "system"))
        r("system.activity", "Devuelve actividad reciente del bus de eventos.", self._cap_activity, tags=("orchestration", "system"))

    def execute(self, capability: str, params: dict[str, Any] | None = None, *, confirmed: bool = False) -> ActionResult:
        return self.registry.execute(capability, params or {}, confirmed=confirmed)

    def run_routine(self, name: str, variables: dict[str, Any] | None = None, asynchronous: bool = False) -> ActionResult:
        return self.routines.run(name, variables or {}, asynchronous=asynchronous)

    def manage_mode(self, operation: str, name: str = "") -> ActionResult:
        operation = operation.strip().lower()
        if operation in {"start", "on", "activar", "iniciar"}:
            return self.modes.start(name)
        if operation in {"stop", "off", "desactivar", "detener"}:
            return self.modes.stop(name)
        return self.modes.status(name)

    def get_integrations(self) -> dict[str, Any]:
        return self.integrations_store.load()

    def save_integrations(self, config: dict[str, Any]) -> None:
        self.integrations_store.save(config)
        self.event_bus.publish("integrations.saved", {"sections": list(config)}, "platform")

    def status(self) -> dict[str, Any]:
        return {
            "capabilities": len(self.registry.list()),
            "routines": len(self.routines.list()),
            "modes": self.modes.list(),
            "automations": len(self.automations.list()),
            "nodes": self.esp32.list_nodes(),
            "devices": self.esp32.list_devices(),
            "audio": self.audio.load(),
        }

    def tool_call(self, name: str, args: dict[str, Any]) -> ActionResult:
        """Stable bridge used by Gemini Live function calls."""
        if name == "run_routine":
            raw_variables = args.get("variables") or {}
            if isinstance(raw_variables, str):
                try:
                    raw_variables = json.loads(raw_variables) if raw_variables.strip() else {}
                except json.JSONDecodeError:
                    return ActionResult.failure("Las variables de la rutina no son JSON válido.", error="invalid_variables_json")
            return self.run_routine(
                str(args.get("routine", "")),
                dict(raw_variables or {}),
                bool(args.get("asynchronous", False)),
            )
        if name == "manage_mode":
            return self.manage_mode(str(args.get("action", "status")), str(args.get("mode", "")))
        if name == "media_control":
            return self._media_control(args)
        if name == "obs_control":
            return self._obs_control(args)
        if name == "pc_status":
            return self.execute("pc.status", args)
        if name == "email_center":
            return self._email_center(args)
        if name == "notification_center":
            return self._notification_center(args)
        if name == "home_automation":
            return self.execute("domotics.control", args)
        if name == "list_home_devices":
            return self.execute("domotics.list", args)
        return self.execute(name, args, confirmed=bool(args.get("confirmed", False)))

    def _cap_run_routine(self, params: dict[str, Any]) -> ActionResult:
        return self.run_routine(str(params.get("routine", "")), params.get("variables", {}), bool(params.get("asynchronous", False)))

    def _cap_list_routines(self, _params: dict[str, Any]) -> ActionResult:
        items = self.routines.list()
        return ActionResult.success(f"Hay {len(items)} rutinas configuradas.", routines=items)

    def _cap_manage_mode(self, params: dict[str, Any]) -> ActionResult:
        return self.manage_mode(str(params.get("action", "status")), str(params.get("mode", "")))

    def _cap_list_automations(self, _params: dict[str, Any]) -> ActionResult:
        items = self.automations.list()
        return ActionResult.success(f"Hay {len(items)} automatizaciones.", automations=items)

    def _cap_list_capabilities(self, params: dict[str, Any]) -> ActionResult:
        items = self.registry.list(str(params.get("tag", "")) or None)
        return ActionResult.success(f"JARVIS tiene {len(items)} capacidades registradas.", capabilities=items)

    def _cap_activity(self, params: dict[str, Any]) -> ActionResult:
        items = self.event_bus.history(str(params.get("topic", "*")), int(params.get("limit", 30)))
        return ActionResult.success(f"Actividad reciente: {len(items)} eventos.", events=items)

    def _media_control(self, args: dict[str, Any]) -> ActionResult:
        action = str(args.get("action", "status")).lower()
        mapping = {
            "status": "spotify.status",
            "play_track": "spotify.play_track",
            "track": "spotify.play_track",
            "play_playlist": "spotify.play_playlist",
            "playlist": "spotify.play_playlist",
            "play": "spotify.resume",
            "resume": "spotify.resume",
            "pause": "spotify.pause",
            "next": "spotify.next",
            "previous": "spotify.previous",
            "volume": "spotify.set_volume",
            "save": "spotify.save_current",
            "play_pause": "media.play_pause",
        }
        capability = mapping.get(action)
        if not capability:
            return ActionResult.failure(f"Acción multimedia desconocida: {action}")
        result = self.execute(capability, args)
        if not result.ok and action in {"play", "resume", "pause", "next", "previous", "play_pause"}:
            fallback = {
                "play": "media.play_pause",
                "resume": "media.play_pause",
                "pause": "media.play_pause",
                "next": "media.next",
                "previous": "media.previous",
                "play_pause": "media.play_pause",
            }.get(action)
            if fallback:
                fallback_result = self.execute(fallback, args)
                fallback_result.warnings.append(result.message)
                return fallback_result
        return result

    def _obs_control(self, args: dict[str, Any]) -> ActionResult:
        action = str(args.get("action", "status")).lower()
        mapping = {
            "status": "obs.status",
            "open": "obs.open",
            "scene": "obs.set_scene",
            "set_scene": "obs.set_scene",
            "start_recording": "obs.start_recording",
            "stop_recording": "obs.stop_recording",
            "start_stream": "obs.start_stream",
            "stop_stream": "obs.stop_stream",
        }
        capability = mapping.get(action)
        if not capability:
            return ActionResult.failure(f"Acción de OBS desconocida: {action}")
        return self.execute(capability, args, confirmed=bool(args.get("confirmed", False)))

    def _email_center(self, args: dict[str, Any]) -> ActionResult:
        action = str(args.get("action", "unread")).lower()
        mapping = {"status": "gmail.status", "unread": "gmail.unread", "search": "gmail.search", "read": "gmail.read", "mark_read": "gmail.mark_read"}
        capability = mapping.get(action)
        if not capability:
            return ActionResult.failure(f"Acción de correo desconocida: {action}")
        return self.execute(capability, args)

    def _notification_center(self, args: dict[str, Any]) -> ActionResult:
        action = str(args.get("action", "list")).lower()
        mapping = {"list": "notifications.list", "read": "notifications.read", "windows": "notifications.windows", "emit": "notifications.emit"}
        capability = mapping.get(action)
        if not capability:
            return ActionResult.failure(f"Acción de notificaciones desconocida: {action}")
        return self.execute(capability, args)

    def shutdown(self) -> None:
        """Release threads, serial ports and global runtime references."""
        try:
            self.automations.shutdown()
        except Exception:
            pass
        try:
            self.modes.shutdown()
        except Exception:
            pass
        try:
            self.routines.shutdown()
        except Exception:
            pass
        try:
            self.esp32.shutdown()
        except Exception:
            pass
        try:
            self.event_bus.stop()
        except Exception:
            pass
        try:
            from .runtime import set_platform
            set_platform(None)
        except Exception:
            pass

    def _confirm(self, title: str, message: str) -> bool:
        if self.ui and hasattr(self.ui, "confirm_action"):
            try:
                return bool(self.ui.confirm_action(title, message))
            except Exception:
                pass
        return False

    def _log_event(self, event) -> None:
        if not self.ui:
            return
        try:
            if event.topic.endswith("started"):
                self.ui.write_log(f"CORE: {event.topic}")
            elif event.topic.endswith(("completed", "completed_with_warnings", "failed", "finished")):
                self.ui.write_log(f"CORE: {event.topic}")
        except Exception:
            pass
