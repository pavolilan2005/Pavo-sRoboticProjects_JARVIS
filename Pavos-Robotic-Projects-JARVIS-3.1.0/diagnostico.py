"""Diagnóstico local de Pavo's Robotic Projects // JARVIS. No imprime claves ni secretos."""
from __future__ import annotations

import importlib
import json
import platform
import subprocess
import sys
import unittest
from pathlib import Path

from core.subprocess_compat import install_subprocess_text_compat
install_subprocess_text_compat()

BASE = Path(__file__).resolve().parent


def status(ok: bool, label: str, detail: str = "") -> None:
    mark = "OK" if ok else "ERROR"
    suffix = f" — {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")


def main() -> int:
    print("=== DIAGNÓSTICO Pavo's Robotic Projects // JARVIS ===")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Sistema: {platform.platform()}")
    failures = 0
    python_ok = (3, 11) <= sys.version_info < (3, 13)
    status(python_ok, "Python 3.11/3.12 recomendado")
    if not python_ok:
        failures += 1

    required = {
        "google.genai": "google-genai",
        "sounddevice": "sounddevice",
        "PyQt6": "PyQt6",
        "serial": "pyserial",
        "numpy": "numpy",
        "PIL": "Pillow",
        "psutil": "psutil",
        "obsws_python": "obsws-python",
        "spotipy": "spotipy",
        "googleapiclient": "google-api-python-client",
    }
    for module, package in required.items():
        try:
            importlib.import_module(module)
            status(True, package)
        except Exception as exc:
            failures += 1
            status(False, package, f"{type(exc).__name__}: {exc}")

    config = BASE / "config" / "api_keys.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        key_ok = bool(str(data.get("gemini_api_key", "")).strip())
        status(key_ok, "Clave de Gemini configurada")
        status(bool(str(data.get("os_system", "")).strip()), "Sistema operativo configurado")
        if not key_ok:
            failures += 1
    except Exception as exc:
        failures += 1
        status(False, "config/api_keys.json", str(exc))

    for filename in ["nodes.json", "devices.json", "routines.json", "modes.json", "automations.json", "integrations.json"]:
        try:
            json.loads((BASE / "config" / filename).read_text(encoding="utf-8"))
            status(True, f"config/{filename}")
        except Exception as exc:
            failures += 1
            status(False, f"config/{filename}", str(exc))

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs = sum(1 for d in devices if int(d.get("max_input_channels", 0)) > 0)
        outputs = sum(1 for d in devices if int(d.get("max_output_channels", 0)) > 0)
        status(inputs > 0, "Dispositivos de entrada", str(inputs))
        status(outputs > 0, "Dispositivos de salida", str(outputs))
    except Exception as exc:
        status(False, "Enumeración de audio", str(exc))

    try:
        child = "import sys; sys.stdout.buffer.write(bytes([0xA1]))"
        probe = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=5, check=True)
        status(bool(probe.stdout), "Decodificación segura de subprocess")
    except Exception as exc:
        failures += 1
        status(False, "Decodificación segura de subprocess", f"{type(exc).__name__}: {exc}")

    try:
        suite = unittest.defaultTestLoader.discover(str(BASE / "tests"), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        status(result.wasSuccessful(), "Pruebas del núcleo NEXUS", f"{result.testsRun} pruebas")
        if not result.wasSuccessful():
            failures += 1
    except Exception as exc:
        failures += 1
        status(False, "Pruebas del núcleo NEXUS", str(exc))

    print(f"Log: {BASE / 'logs' / 'jarvis.log'}")
    print("====================================")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
