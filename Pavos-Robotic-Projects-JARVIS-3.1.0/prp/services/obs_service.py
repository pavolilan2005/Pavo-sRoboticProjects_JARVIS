from __future__ import annotations
from prp.core.config import ConfigStore
from prp.core.models import ActionResult

class ObsService:
    def __init__(self, config: ConfigStore):
        self.config = config
    def _client(self):
        import obsws_python as obs
        cfg = (self.config.load("integrations.json", {}) or {}).get("obs", {})
        secret = self.config.secrets().get("obs_password", "")
        return obs.ReqClient(host=cfg.get("host", "127.0.0.1"), port=int(cfg.get("port", 4455)), password=secret, timeout=int(cfg.get("timeout", 5)))
    def status(self) -> ActionResult:
        try:
            version = self._client().get_version()
            return ActionResult.success("OBS conectado", obs_version=getattr(version, "obs_version", ""))
        except Exception as exc: return ActionResult.failure("OBS no disponible", str(exc))
    def scene(self, scene: str) -> ActionResult:
        try:
            self._client().set_current_program_scene(scene)
            return ActionResult.success(f"Escena activa: {scene}")
        except Exception as exc: return ActionResult.failure(f"No pude cambiar a {scene}", str(exc))
    def record_start(self) -> ActionResult:
        try: self._client().start_record(); return ActionResult.success("Grabación iniciada")
        except Exception as exc: return ActionResult.failure("No pude iniciar grabación", str(exc))
    def record_stop(self) -> ActionResult:
        try:
            response = self._client().stop_record()
            return ActionResult.success("Grabación detenida", path=getattr(response, "output_path", ""))
        except Exception as exc: return ActionResult.failure("No pude detener grabación", str(exc))
