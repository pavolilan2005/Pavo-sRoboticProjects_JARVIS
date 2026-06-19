from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from prp_core.storage import JsonStore

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover
    sd = None


DEFAULT_AUDIO_SETTINGS = {
    "version": 1,
    "input_device": None,
    "output_device": None,
    "sensitivity": 82,
    "input_gain": 1.20,
    "vad_enabled": True,
    "min_rms": 12.0,
    "max_rms": 6000.0,
    "calibration_seconds": 1.2,
    "speech_trail_seconds": 1.25,
    "preroll_chunks": 6,
    "output_sample_rate": None,
}


class AudioSettingsAdapter:
    """Single source of truth for user-facing audio configuration.

    The adapter owns device discovery and persistent settings. The Gemini runtime
    remains the sole owner of open microphone/speaker streams; this class only
    notifies it when settings change or a calibration is requested.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.store = JsonStore(
            self.base_dir / "config" / "audio.json",
            DEFAULT_AUDIO_SETTINGS,
        )
        self._apply_callback: Callable[[dict[str, Any]], None] | None = None
        self._calibrate_callback: Callable[[], None] | None = None
        self._status_callback: Callable[[], dict[str, Any]] | None = None

    def bind_runtime(
        self,
        *,
        apply_callback: Callable[[dict[str, Any]], None] | None = None,
        calibrate_callback: Callable[[], None] | None = None,
        status_callback: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._apply_callback = apply_callback
        self._calibrate_callback = calibrate_callback
        self._status_callback = status_callback

    def load(self) -> dict[str, Any]:
        raw = self.store.load()
        merged = deepcopy(DEFAULT_AUDIO_SETTINGS)
        if isinstance(raw, dict):
            merged.update(raw)
        return self._validate(merged)

    def save(self, settings: dict[str, Any]) -> dict[str, Any]:
        merged = self.load()
        merged.update(dict(settings or {}))
        clean = self._validate(merged)
        self.store.save(clean)
        if self._apply_callback:
            self._apply_callback(dict(clean))
        return clean

    def request_calibration(self) -> None:
        if self._calibrate_callback:
            self._calibrate_callback()

    def runtime_status(self) -> dict[str, Any]:
        if self._status_callback:
            try:
                return dict(self._status_callback() or {})
            except Exception as exc:  # pragma: no cover - runtime only
                return {"error": str(exc)}
        return {}

    def list_devices(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "inputs": [],
            "outputs": [],
            "default_input": None,
            "default_output": None,
        }
        if sd is None:
            result["error"] = "sounddevice no está instalado"
            return result

        try:
            default_pair = sd.default.device
            if isinstance(default_pair, (list, tuple)) and len(default_pair) >= 2:
                result["default_input"] = self._coerce_device(default_pair[0])
                result["default_output"] = self._coerce_device(default_pair[1])
        except Exception:
            pass

        try:
            devices = sd.query_devices()
        except Exception as exc:
            result["error"] = str(exc)
            return result

        for index, device in enumerate(devices):
            item = {
                "index": index,
                "name": str(device.get("name", f"Dispositivo {index}")),
                "hostapi": int(device.get("hostapi", -1)),
                "default_samplerate": int(round(float(device.get("default_samplerate", 0) or 0))),
                "max_input_channels": int(device.get("max_input_channels", 0) or 0),
                "max_output_channels": int(device.get("max_output_channels", 0) or 0),
            }
            if item["max_input_channels"] > 0:
                result["inputs"].append(dict(item))
            if item["max_output_channels"] > 0:
                result["outputs"].append(dict(item))
        return result

    @staticmethod
    def _coerce_device(value: Any) -> int | str | None:
        if value in (None, "", -1, "-1"):
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if text.lstrip("-").isdigit():
            number = int(text)
            return None if number < 0 else number
        return text or None

    def _validate(self, settings: dict[str, Any]) -> dict[str, Any]:
        clean = deepcopy(DEFAULT_AUDIO_SETTINGS)
        clean.update(settings)
        clean["version"] = 1
        clean["input_device"] = self._coerce_device(clean.get("input_device"))
        clean["output_device"] = self._coerce_device(clean.get("output_device"))
        clean["sensitivity"] = max(1, min(100, int(clean.get("sensitivity", 82))))
        clean["input_gain"] = max(0.25, min(4.0, float(clean.get("input_gain", 1.2))))
        clean["vad_enabled"] = bool(clean.get("vad_enabled", True))
        clean["min_rms"] = max(1.0, min(2000.0, float(clean.get("min_rms", 12.0))))
        clean["max_rms"] = max(clean["min_rms"], min(30000.0, float(clean.get("max_rms", 6000.0))))
        clean["calibration_seconds"] = max(0.25, min(5.0, float(clean.get("calibration_seconds", 1.2))))
        clean["speech_trail_seconds"] = max(0.25, min(4.0, float(clean.get("speech_trail_seconds", 1.25))))
        clean["preroll_chunks"] = max(1, min(30, int(clean.get("preroll_chunks", 6))))
        output_rate = clean.get("output_sample_rate")
        if output_rate in (None, "", 0, "0"):
            clean["output_sample_rate"] = None
        else:
            clean["output_sample_rate"] = max(8000, min(192000, int(output_rate)))
        return clean
