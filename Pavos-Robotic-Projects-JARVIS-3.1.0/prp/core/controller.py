from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .automations import AutomationEngine
from .capabilities import CapabilityRegistry
from .event_bus import EventBus
from .models import ActionResult
from .modes import ModeManager
from .media_intelligence import MediaIntelligence
from .routines import RoutineEngine
from .storage import JsonStore
from prp.adapters.apps import AppsAdapter
from prp.adapters.esp32 import ESP32Adapter
from prp.adapters.gmail import GmailAdapter
from prp.adapters.media import MediaAdapter
from prp.adapters.notifications import NotificationsAdapter
from prp.adapters.obs import OBSAdapter
from prp.adapters.pc import PCAdapter
from prp.adapters.spotify import SpotifyAdapter
from prp.adapters.tasks import TasksAdapter


DEFAULT_INTEGRATIONS = {
    "version": 1,
    "obs": {"host": "127.0.0.1", "port": 4455, "password": "", "timeout": 5},
    "spotify": {"client_id": "", "client_secret": "", "redirect_uri": "http://127.0.0.1:8888/callback", "preferred_device": ""},
    "gmail": {"credentials_path": "config/gmail_credentials.json", "token_path": "config/gmail_token.json"},
    "windows_notifications": {"enabled": False},
}


class PRPPlatform:
    """Central capability layer. UI, voice, routines and automations all use it."""

    def __init__(self, base_dir: str | Path, config_manager, ui=None):
        self.base_dir = Path(base_dir)
        self.config_manager = config_manager
        self.ui = ui
        self.event_bus = EventBus()
        self.integrations_store = JsonStore(self.base_dir / "config" / "integrations.json", DEFAULT_INTEGRATIONS)
        self.registry = CapabilityRegistry(self.event_bus, confirmer=self._confirm)
        self._audio_service = None
        self._audio_restart = None
        self._audio_lock = threading.RLock()

        self.apps = AppsAdapter(self.registry, self.event_bus, ui)
        self.pc = PCAdapter(self.registry, self.event_bus, ui)
        self.media = MediaAdapter(self.registry, self.event_bus)
        self.notifications = NotificationsAdapter(self.registry, self.event_bus, ui)
        self.obs = OBSAdapter(self.registry, self.event_bus, self.get_integrations, ui)
        self.spotify = SpotifyAdapter(self.registry, self.event_bus, self.get_integrations, self.base_dir)
        self.media_intelligence = MediaIntelligence(self.base_dir, self.spotify, self.event_bus)
        self.gmail = GmailAdapter(self.registry, self.event_bus, self.get_integrations, self.base_dir)
        self.esp32 = ESP32Adapter(self.registry, self.event_bus, self.base_dir, ui=ui)
        self.tasks = TasksAdapter(self.registry, self.event_bus, self.base_dir)

        for adapter in (self.apps, self.pc, self.media, self.notifications, self.obs, self.spotify, self.gmail, self.esp32, self.tasks):
            adapter.register()
        self.media_intelligence.register(self.registry)

        self.routines = RoutineEngine(self.registry, self.event_bus, self.base_dir / "config" / "routines.json")
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
        from .runtime import set_platform
        set_platform(self)

    def attach_audio(self, service, restart_callback=None) -> None:
        with self._audio_lock:
            self._audio_service = service
            self._audio_restart = restart_callback

    def _register_orchestration_capabilities(self) -> None:
        r = self.registry.register_handler
        r("routine.run", "Ejecuta una rutina configurable por nombre.", self._cap_run_routine, tags=("orchestration", "routine"))
        r("routine.list", "Lista las rutinas configuradas.", self._cap_list_routines, tags=("orchestration", "routine"))
        r("mode.manage", "Activa, desactiva o consulta modos persistentes.", self._cap_manage_mode, tags=("orchestration", "mode"))
        r("automation.list", "Lista automatizaciones configuradas.", self._cap_list_automations, tags=("orchestration", "automation"))
        r("system.capabilities", "Lista las capacidades registradas.", self._cap_list_capabilities, tags=("orchestration", "system"))
        r("system.activity", "Devuelve actividad reciente.", self._cap_activity, tags=("orchestration", "system"))

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
        try:
            self.spotify.invalidate_client()
        except Exception:
            pass
        self.event_bus.publish("integrations.saved", {"sections": list(config)}, "platform")

    def get_audio_settings(self) -> dict[str, Any]:
        app = self.config_manager.load("app.json", {}) or {}
        return deepcopy(app.get("audio", {}))

    def save_audio_settings(self, settings: dict[str, Any], restart: bool = True) -> dict[str, Any]:
        app = self.config_manager.load("app.json", {}) or {}
        app["audio"] = dict(settings)
        self.config_manager.save("app.json", app)
        with self._audio_lock:
            service = self._audio_service
            callback = self._audio_restart
        if service is not None:
            service.update_settings(settings)
        if restart and callback:
            callback()
        self.event_bus.publish("audio.settings.saved", {"settings": dict(settings)}, "platform")
        return dict(settings)

    def audio_devices(self) -> dict[str, Any]:
        with self._audio_lock:
            service = self._audio_service
        if service is None:
            return {"devices": [], "defaults": (-1, -1), "status": {}}
        return {"devices": service.devices(), "defaults": service.defaults(), "status": service.status()}

    def audio_test(self, seconds: float = 4.0) -> ActionResult:
        with self._audio_lock:
            service = self._audio_service
        if service is None:
            return ActionResult.failure("El servicio de audio no está disponible.")
        try:
            recording, rate, peak, rms = service.record_test(seconds)
            service.play_test(recording, rate)
            return ActionResult.success(f"Prueba de audio terminada. RMS={rms:.1f}, pico={peak}.", rms=rms, peak=peak, rate=rate)
        except Exception as exc:
            return ActionResult.failure(f"Falló la prueba de audio: {exc}", error=str(exc))

    def status(self) -> dict[str, Any]:
        return {
            "capabilities": len(self.registry.list()),
            "routines": len(self.routines.list()),
            "modes": self.modes.list(),
            "automations": len(self.automations.list()),
            "nodes": self.esp32.list_nodes(),
            "devices": self.esp32.list_devices(),
            "tasks": self.tasks.list(),
            "media_aliases": self.media_intelligence.list_aliases(),
            "media_context": self.media_intelligence.state_store.load(),
            "audio": self.audio_devices().get("status", {}),
        }

    def tool_call(self, name: str, args: dict[str, Any]) -> ActionResult:
        if name == "run_routine":
            variables = args.get("variables") or {}
            if isinstance(variables, str):
                try:
                    variables = json.loads(variables) if variables.strip() else {}
                except json.JSONDecodeError:
                    return ActionResult.failure("Las variables de la rutina no son JSON válido.")
            return self.run_routine(str(args.get("routine", "")), dict(variables), bool(args.get("asynchronous", False)))
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
        if name == "task_manager":
            action = str(args.get("action", "list")).lower()
            mapping = {"create": "tasks.create", "list": "tasks.list", "complete": "tasks.complete", "delete": "tasks.delete"}
            return self.execute(mapping.get(action, "tasks.list"), args)
        return self.execute(name, args, confirmed=bool(args.get("confirmed", False)))

    def _media_control(self, args: dict[str, Any]) -> ActionResult:
        args = dict(args or {})
        action = str(args.get("action", "status")).strip().lower()
        action_aliases = {
            "reproducir": "smart_play", "pon": "smart_play", "buscar": "smart_play",
            "smart": "smart_play", "play_music": "smart_play",
            "cancion": "play_track", "track": "play_track",
            "lista": "play_playlist", "playlist": "play_playlist",
            "artista": "play_artist", "artist": "play_artist",
            "album": "play_album", "disco": "play_album",
            "otra_del_artista": "another_by_artist", "same_artist": "another_by_artist",
            "siguiente": "next", "anterior": "previous", "pausar": "pause",
            "reanudar": "resume", "volumen": "volume", "guardar": "save",
            "playlists": "list_playlists", "alias": "aliases", "contexto": "context",
        }
        action = action_aliases.get(action, action)
        has_target = any(str(args.get(key, "")).strip() for key in (
            "query", "track", "playlist", "artist", "album", "alias", "relation"
        ))
        if action in {"play", "resume"} and has_target:
            action = "smart_play"

        mapping = {
            "status": "spotify.status",
            "smart_play": "media.smart_play",
            "play_track": "media.smart_play",
            "play_playlist": "media.smart_play",
            "play_artist": "media.smart_play",
            "play_album": "media.smart_play",
            "another_by_artist": "media.smart_play",
            "play": "spotify.resume",
            "resume": "spotify.resume",
            "pause": "spotify.pause",
            "next": "spotify.next",
            "previous": "spotify.previous",
            "volume": "spotify.set_volume",
            "save": "spotify.save_current",
            "play_pause": "media.play_pause",
            "list_playlists": "media.playlists.list",
            "aliases": "media.aliases.list",
            "context": "media.context",
            "clear_context": "media.context.clear",
        }
        if action == "play_track":
            args.setdefault("target_type", "track")
        elif action == "play_playlist":
            args.setdefault("target_type", "playlist")
        elif action == "play_artist":
            args.setdefault("target_type", "artist")
        elif action == "play_album":
            args.setdefault("target_type", "album")
        elif action == "another_by_artist":
            args.setdefault("relation", "same_artist")

        capability = mapping.get(action)
        if not capability:
            return ActionResult.failure(f"Acción multimedia desconocida: {action}")
        result = self.execute(capability, args)
        if result.ok and action == "status" and result.data.get("active") and result.data.get("uri"):
            try:
                self.media_intelligence._remember_result(result, "track", source="spotify_status")
            except Exception:
                pass
        if not result.ok and action in {"play", "resume", "pause", "next", "previous", "play_pause"}:
            fallback = {
                "play": "media.play_pause", "resume": "media.play_pause", "pause": "media.play_pause",
                "next": "media.next", "previous": "media.previous", "play_pause": "media.play_pause",
            }.get(action)
            if fallback:
                return self.execute(fallback, args)
        return result

    def _obs_control(self, args: dict[str, Any]) -> ActionResult:
        action = str(args.get("action", "status")).lower()
        mapping = {
            "status": "obs.status", "open": "obs.open", "scene": "obs.set_scene", "set_scene": "obs.set_scene",
            "start_recording": "obs.start_recording", "stop_recording": "obs.stop_recording",
            "start_stream": "obs.start_stream", "stop_stream": "obs.stop_stream",
        }
        capability = mapping.get(action)
        if not capability:
            return ActionResult.failure(f"Acción de OBS desconocida: {action}")
        return self.execute(capability, args, confirmed=bool(args.get("confirmed", False)))

    def _email_center(self, args: dict[str, Any]) -> ActionResult:
        action = str(args.get("action", "unread")).lower()
        mapping = {"status": "gmail.status", "unread": "gmail.unread", "search": "gmail.search", "read": "gmail.read", "mark_read": "gmail.mark_read"}
        return self.execute(mapping.get(action, "gmail.unread"), args)

    def _notification_center(self, args: dict[str, Any]) -> ActionResult:
        action = str(args.get("action", "list")).lower()
        mapping = {"list": "notifications.list", "read": "notifications.read", "windows": "notifications.windows", "emit": "notifications.emit"}
        return self.execute(mapping.get(action, "notifications.list"), args)

    def _cap_run_routine(self, params):
        return self.run_routine(str(params.get("routine", "")), params.get("variables", {}), bool(params.get("asynchronous", False)))

    def _cap_list_routines(self, _params):
        items = self.routines.list()
        return ActionResult.success(f"Hay {len(items)} rutinas configuradas.", routines=items)

    def _cap_manage_mode(self, params):
        return self.manage_mode(str(params.get("action", "status")), str(params.get("mode", "")))

    def _cap_list_automations(self, _params):
        items = self.automations.list()
        return ActionResult.success(f"Hay {len(items)} automatizaciones.", automations=items)

    def _cap_list_capabilities(self, params):
        items = self.registry.list(str(params.get("tag", "")) or None)
        return ActionResult.success(f"JARVIS tiene {len(items)} capacidades registradas.", capabilities=items)

    def _cap_activity(self, params):
        items = self.event_bus.history(str(params.get("topic", "*")), int(params.get("limit", 30)))
        return ActionResult.success(f"Actividad reciente: {len(items)} eventos.", events=items)

    def _confirm(self, capability, params) -> bool:
        if self.ui and hasattr(self.ui, "confirm_action"):
            return bool(self.ui.confirm_action("Confirmar acción", f"¿Ejecutar {capability.name}?"))
        return False

    def shutdown(self) -> None:
        for fn in (self.automations.shutdown, self.modes.shutdown, self.esp32.shutdown, self.event_bus.stop):
            try:
                fn()
            except Exception:
                pass
