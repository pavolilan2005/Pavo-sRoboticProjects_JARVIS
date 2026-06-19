from __future__ import annotations

import json
import platform
import sys
from pathlib import Path


def check_import(name: str):
    try:
        __import__(name)
        return "OK"
    except Exception as exc:
        return f"ERROR: {exc}"


base = Path(__file__).resolve().parent
print("Pavo's Robotic Projects // JARVIS 3.0.0")
print("Python:", sys.version)
print("Sistema:", platform.platform())
for name in ["PyQt6", "sounddevice", "numpy", "serial", "psutil", "spotipy", "obsws_python", "google.genai"]:
    print(f"{name:18}", check_import(name))

for filename in ["app.json", "nodes.json", "devices.json", "routines.json", "modes.json", "integrations.json"]:
    path = base / "config" / filename
    try:
        json.loads(path.read_text(encoding="utf-8"))
        print(f"config/{filename:20} OK")
    except Exception as exc:
        print(f"config/{filename:20} ERROR: {exc}")

try:
    import sounddevice as sd
    print("Audio defaults:", sd.default.device)
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] or dev["max_output_channels"]:
            print(i, dev["name"], "IN", dev["max_input_channels"], "OUT", dev["max_output_channels"], "RATE", dev["default_samplerate"])
except Exception as exc:
    print("Audio devices ERROR:", exc)

try:
    from serial.tools import list_ports
    print("Puertos seriales:", [(p.device, p.description) for p in list_ports.comports()])
except Exception as exc:
    print("Serial ERROR:", exc)
