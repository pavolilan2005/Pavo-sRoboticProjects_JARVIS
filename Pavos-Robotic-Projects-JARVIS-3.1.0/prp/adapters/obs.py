from __future__ import annotations

from typing import Any

from prp.core.models import ActionResult, RiskLevel


class OBSAdapter:
    def __init__(self, registry, event_bus, config_getter, ui=None):
        self.registry = registry
        self.event_bus = event_bus
        self.config_getter = config_getter
        self.ui = ui

    def register(self) -> None:
        r = self.registry.register_handler
        r("obs.status", "Consulta conexión, escena, grabación y transmisión de OBS.", self.status, tags=("obs", "stream"))
        r("obs.open", "Abre OBS Studio.", self.open_obs, tags=("obs", "stream"))
        r("obs.set_scene", "Cambia la escena activa de OBS.", self.set_scene, tags=("obs", "stream"))
        r("obs.start_recording", "Inicia la grabación en OBS.", self.start_recording, risk=RiskLevel.MEDIUM, tags=("obs", "stream"))
        r("obs.stop_recording", "Detiene la grabación en OBS.", self.stop_recording, tags=("obs", "stream"))
        r("obs.start_stream", "Inicia la transmisión en OBS.", self.start_stream, risk=RiskLevel.CRITICAL, requires_confirmation=True, tags=("obs", "stream"))
        r("obs.stop_stream", "Detiene la transmisión en OBS.", self.stop_stream, risk=RiskLevel.HIGH, requires_confirmation=True, tags=("obs", "stream"))

    def _config(self) -> dict[str, Any]:
        return dict(self.config_getter().get("obs") or {})

    def _client(self):
        try:
            import obsws_python as obs
        except ImportError as exc:
            raise RuntimeError("Falta obsws-python. Ejecuta INSTALAR_JARVIS.bat nuevamente.") from exc
        cfg = self._config()
        return obs.ReqClient(
            host=str(cfg.get("host", "localhost")),
            port=int(cfg.get("port", 4455)),
            password=str(cfg.get("password", "")),
            timeout=float(cfg.get("timeout", 5)),
        )

    def open_obs(self, _params: dict[str, Any]) -> ActionResult:
        try:
            import subprocess
            from pathlib import Path
            path = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")
            if not path.exists():
                return ActionResult.failure("No encontré OBS en la ruta predeterminada. Ábrelo una vez o ajusta la instalación.")
            subprocess.Popen([str(path)], cwd=str(path.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ActionResult.success("OBS abierto.")
        except Exception as exc:
            return ActionResult.failure(f"No pude abrir OBS: {exc}")

    def status(self, _params: dict[str, Any]) -> ActionResult:
        try:
            client = self._client()
            version = client.get_version()
            scene = client.get_current_program_scene()
            record = client.get_record_status()
            stream = client.get_stream_status()
            data = {
                "connected": True,
                "obs_version": getattr(version, "obs_version", ""),
                "websocket_version": getattr(version, "obs_web_socket_version", ""),
                "scene": getattr(scene, "current_program_scene_name", ""),
                "recording": bool(getattr(record, "output_active", False)),
                "streaming": bool(getattr(stream, "output_active", False)),
            }
            return ActionResult.success(
                f"OBS conectado. Escena {data['scene'] or 'desconocida'}, grabación {'activa' if data['recording'] else 'detenida'}, stream {'activo' if data['streaming'] else 'detenido'}.",
                **data,
            )
        except Exception as exc:
            return ActionResult.failure(
                f"No pude conectar con OBS WebSocket: {exc}. Revisa Herramientas > Ajustes de obs-websocket.",
                error=str(exc),
                connected=False,
            )

    def set_scene(self, params: dict[str, Any]) -> ActionResult:
        scene = str(params.get("scene", "")).strip()
        if not scene:
            return ActionResult.failure("Falta el nombre de la escena.")
        try:
            self._client().set_current_program_scene(scene)
            return ActionResult.success(f"Escena de OBS cambiada a '{scene}'.", scene=scene)
        except Exception as exc:
            return ActionResult.failure(f"No pude cambiar la escena de OBS: {exc}", error=str(exc))

    def start_recording(self, _params: dict[str, Any]) -> ActionResult:
        try:
            self._client().start_record()
            return ActionResult.success("Grabación de OBS iniciada.")
        except Exception as exc:
            return ActionResult.failure(f"No pude iniciar la grabación: {exc}", error=str(exc))

    def stop_recording(self, _params: dict[str, Any]) -> ActionResult:
        try:
            response = self._client().stop_record()
            path = getattr(response, "output_path", "")
            return ActionResult.success("Grabación de OBS detenida.", output_path=path)
        except Exception as exc:
            return ActionResult.failure(f"No pude detener la grabación: {exc}", error=str(exc))

    def start_stream(self, _params: dict[str, Any]) -> ActionResult:
        try:
            self._client().start_stream()
            return ActionResult.success("Transmisión de OBS iniciada.")
        except Exception as exc:
            return ActionResult.failure(f"No pude iniciar la transmisión: {exc}", error=str(exc))

    def stop_stream(self, _params: dict[str, Any]) -> ActionResult:
        try:
            self._client().stop_stream()
            return ActionResult.success("Transmisión de OBS detenida.")
        except Exception as exc:
            return ActionResult.failure(f"No pude detener la transmisión: {exc}", error=str(exc))
