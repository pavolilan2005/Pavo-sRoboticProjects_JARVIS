from pathlib import Path
import compileall
import json

print("=== Pavo's Robotic Projects — JARVIS diagnóstico ===")
root = Path(__file__).parent
print("Versión:", (root / "VERSION.txt").read_text(encoding="utf-8").strip())
print("Compilación:", compileall.compile_dir(root, quiet=1))

secrets_path = root / "config" / "secrets.json"
try:
    secrets = json.loads(secrets_path.read_text(encoding="utf-8")) if secrets_path.exists() else {}
    print("Gemini API key configurada:", bool(str(secrets.get("gemini_api_key", "")).strip()))
except Exception as error:
    print("Configuración ERROR:", error)

try:
    import sounddevice as sd
    print("Audio default:", sd.default.device)
    for index, device in enumerate(sd.query_devices()):
        print(
            index,
            device["name"],
            "IN",
            device["max_input_channels"],
            "OUT",
            device["max_output_channels"],
            int(device["default_samplerate"]),
        )
except Exception as error:
    print("Audio ERROR:", error)

try:
    from google import genai
    print("google-genai OK")
except Exception as error:
    print("Gemini SDK ERROR:", error)
