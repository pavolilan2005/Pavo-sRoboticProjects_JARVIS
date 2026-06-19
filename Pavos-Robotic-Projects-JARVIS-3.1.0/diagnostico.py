from pathlib import Path
import json, importlib
root=Path(__file__).resolve().parent
print("Pavo's Robotic Projects Assistant — Diagnóstico")
for module in ["PyQt6","sounddevice","numpy","serial","psutil","spotipy","obsws_python","google.genai"]:
    try: importlib.import_module(module); print("OK",module)
    except Exception as e: print("FALTA",module,e)
for name in ["app.json","integrations.json","nodes.json","devices.json","routines.json","modes.json","scenes.json"]:
    try: json.loads((root/"config"/name).read_text(encoding="utf-8")); print("JSON OK",name)
    except Exception as e: print("JSON ERROR",name,e)
