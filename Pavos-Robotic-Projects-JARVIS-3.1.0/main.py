import asyncio
import re
import math
import threading
import queue
import logging
import json
import os
import sys
import time
import unicodedata
import warnings
from pathlib import Path
from collections import deque
from logging.handlers import RotatingFileHandler

# Install tolerant decoding before importing the UI/actions. Windows tools can
# emit CP1252/OEM bytes even when Python itself runs in UTF-8 mode.
from core.subprocess_compat import install_subprocess_text_compat
install_subprocess_text_compat()

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        import audioop as _audioop
    except ImportError:  # Python 3.13+ removed audioop
        _audioop = None

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
)
from mark_core import MarkPlatform

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater

try:
    import serial
except ImportError:
    serial = None


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LOG_PATH        = BASE_DIR / "logs" / "jarvis.log"
LIVE_MODEL      = os.getenv(
    "JARVIS_LIVE_MODEL",
    "models/gemini-2.5-flash-native-audio-preview-12-2025",
)
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("jarvis")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


LOGGER = _setup_logging()

# --- ESP32 / Domótica serial settings ---------------------------------------
ESP32_CONFIG_PATH = BASE_DIR / "config" / "esp32_serial.json"
DOMOTICS_CONFIG_PATH = BASE_DIR / "config" / "domotics_devices.json"
ESP32_BAUDRATE = int(os.getenv("JARVIS_ESP32_BAUDRATE", "115200"))
ESP32_TIMEOUT = float(os.getenv("JARVIS_ESP32_TIMEOUT", "1.2"))
ESP32_BOOT_WAIT = float(os.getenv("JARVIS_ESP32_BOOT_WAIT", "1.4"))
ESP32_HEALTH_INTERVAL = float(os.getenv("JARVIS_ESP32_HEALTH_INTERVAL", "10"))
ESP32_AUTO_DETECT = os.getenv("JARVIS_ESP32_AUTO_DETECT", "1") != "0"

DEFAULT_DOMOTICS_CONFIG = {
    "devices": {
        "foco": {
            "aliases": ["foco", "luz", "luces", "lampara", "lámpara", "led"],
            "commands": {"on": "C", "off": "A", "toggle": "T", "status": "E"},
            "responses": {
                "ACK:FOCO_ON": "Foco encendido.",
                "ACK:FOCO_OFF": "Foco apagado.",
                "ESTADO:FOCO_ON": "El foco está encendido.",
                "ESTADO:FOCO_OFF": "El foco está apagado."
            }
        }
    }
}

ACTION_ALIASES = {
    "on": "on", "prender": "on", "prende": "on", "encender": "on",
    "enciende": "on", "activar": "on", "activa": "on",
    "off": "off", "apagar": "off", "apaga": "off",
    "desactivar": "off", "desactiva": "off",
    "toggle": "toggle", "cambiar": "toggle", "cambia": "toggle",
    "alternar": "toggle", "estado": "status", "status": "status",
    "consultar": "status", "revisar": "status",
}


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON without risking a half-written configuration file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    temp_path.replace(path)


def _load_saved_esp32_port() -> str:
    env_port = os.getenv("JARVIS_ESP32_PORT", "").strip()
    if env_port:
        return env_port
    try:
        if ESP32_CONFIG_PATH.exists():
            data = json.loads(ESP32_CONFIG_PATH.read_text(encoding="utf-8"))
            return str(data.get("port", "")).strip()
    except Exception as exc:
        LOGGER.warning("Could not read ESP32 config: %s", exc)
    return "COM6"


ESP32_PORT = _load_saved_esp32_port()
_esp32_serial = None
_esp32_lock = threading.RLock()


def _save_esp32_port(port: str) -> None:
    try:
        _atomic_write_json(ESP32_CONFIG_PATH, {"port": port})
    except Exception as exc:
        LOGGER.warning("Could not save ESP32 port: %s", exc)


def _load_domotics_config() -> dict:
    try:
        if DOMOTICS_CONFIG_PATH.exists():
            loaded = json.loads(DOMOTICS_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded.get("devices"), dict):
                return loaded
    except Exception as exc:
        LOGGER.warning("Invalid domotics config, using defaults: %s", exc)
    return DEFAULT_DOMOTICS_CONFIG


def _dispatch_ui(player, method: str, *args) -> None:
    """Use JarvisLive's UI queue when available; otherwise call defensively."""
    if player is None:
        return
    dispatcher = getattr(player, "_jarvis_dispatch", None)
    if callable(dispatcher):
        dispatcher(method, *args)
        return
    fn = getattr(player, method, None)
    if callable(fn):
        try:
            fn(*args)
        except Exception:
            LOGGER.debug("UI call failed: %s", method, exc_info=True)


def _list_esp32_ports() -> list[dict[str, str]]:
    """Return available serial ports with enough metadata for auto-detection."""
    if serial is None:
        return []
    try:
        from serial.tools import list_ports
        return [
            {
                "port": p.device,
                "description": p.description or p.device,
                "hwid": p.hwid or "",
                "manufacturer": p.manufacturer or "",
            }
            for p in list_ports.comports()
        ]
    except Exception as exc:
        LOGGER.warning("Could not enumerate serial ports: %s", exc)
        return []


def _autodetect_esp32_port() -> str | None:
    ports = _list_esp32_ports()
    if not ports:
        return None

    available = {p["port"] for p in ports}
    if ESP32_PORT in available:
        return ESP32_PORT
    if not ESP32_AUTO_DETECT:
        return None

    keywords = (
        "cp210", "ch340", "ch341", "usb serial", "silicon labs",
        "wch", "uart", "esp32", "ftdi",
    )
    ranked: list[tuple[int, str]] = []
    for p in ports:
        haystack = " ".join(
            (p.get("description", ""), p.get("hwid", ""), p.get("manufacturer", ""))
        ).lower()
        score = sum(1 for word in keywords if word in haystack)
        ranked.append((score, p["port"]))

    ranked.sort(reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    if len(ports) == 1:
        return ports[0]["port"]
    return None


def _set_esp32_port(port: str) -> str:
    """Change the selected ESP32 serial port and force a reconnect."""
    global ESP32_PORT, _esp32_serial
    port = (port or "").strip()
    if not port:
        return "Puerto inválido."

    with _esp32_lock:
        try:
            if _esp32_serial is not None and _esp32_serial.is_open:
                _esp32_serial.close()
        except Exception:
            LOGGER.debug("Error closing previous serial port", exc_info=True)
        _esp32_serial = None
        ESP32_PORT = port
        _save_esp32_port(port)
    return f"Puerto ESP32 seleccionado: {ESP32_PORT}"


def _set_ui_esp32_status(player, status: str, message: str = "") -> None:
    _dispatch_ui(player, "set_esp32_status", status, ESP32_PORT, message)


def _close_esp32() -> None:
    global _esp32_serial
    with _esp32_lock:
        try:
            if _esp32_serial is not None and _esp32_serial.is_open:
                _esp32_serial.close()
        except Exception:
            LOGGER.debug("Error closing ESP32 serial port", exc_info=True)
        finally:
            _esp32_serial = None


def _connect_esp32() -> tuple[bool, str]:
    """Open/reopen the USB serial link with automatic port recovery."""
    global ESP32_PORT, _esp32_serial

    if serial is None:
        return False, "PySerial no está instalado. Ejecuta: pip install pyserial"

    with _esp32_lock:
        try:
            if _esp32_serial is not None and _esp32_serial.is_open:
                return True, f"ESP32 ya conectada en {ESP32_PORT}"

            detected_port = _autodetect_esp32_port()
            if detected_port and detected_port != ESP32_PORT:
                ESP32_PORT = detected_port
                _save_esp32_port(ESP32_PORT)
                LOGGER.info("ESP32 port auto-detected: %s", ESP32_PORT)

            _esp32_serial = serial.Serial(
                ESP32_PORT,
                ESP32_BAUDRATE,
                timeout=0.12,
                write_timeout=0.5,
            )
            time.sleep(ESP32_BOOT_WAIT)
            _esp32_serial.reset_input_buffer()
            _esp32_serial.reset_output_buffer()
            return True, f"ESP32 conectada en {ESP32_PORT}"

        except Exception as exc:
            _close_esp32()
            return False, f"No se pudo conectar con la ESP32 en {ESP32_PORT}: {exc}"


def _send_esp32_command(
    command: str,
    wait_seconds: float = ESP32_TIMEOUT,
    player=None,
    *,
    show_connecting: bool = True,
) -> tuple[bool, str]:
    """Send a command and wait for ACK/ESTADO/ERR without stale serial data."""
    global _esp32_serial

    command = (command or "").strip()
    if not command:
        return False, "COMANDO_ESP32_VACIO"

    if show_connecting:
        _set_ui_esp32_status(player, "CONNECTING", "probando enlace serial")

    ok, msg = _connect_esp32()
    if not ok:
        _set_ui_esp32_status(player, "DISCONNECTED", msg)
        return False, msg

    with _esp32_lock:
        try:
            _esp32_serial.reset_input_buffer()
            _esp32_serial.write(command.encode("utf-8"))
            _esp32_serial.flush()

            lines: list[str] = []
            deadline = time.monotonic() + max(0.1, wait_seconds)
            while time.monotonic() < deadline:
                if _esp32_serial.in_waiting:
                    line = _esp32_serial.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        lines.append(line)
                        if line.startswith(("ACK:", "ESTADO:", "ERR:")):
                            break
                else:
                    time.sleep(0.02)

            if not lines:
                _close_esp32()
                msg = "SIN_RESPUESTA_DE_ESP32"
                _set_ui_esp32_status(player, "DISCONNECTED", msg)
                return False, msg

            response = "\n".join(lines)
            _set_ui_esp32_status(player, "ONLINE", response)
            return (not response.startswith("ERR:")), response

        except Exception as exc:
            _close_esp32()
            msg = f"ERROR_SERIAL_ESP32: {exc}"
            _set_ui_esp32_status(player, "DISCONNECTED", msg)
            return False, msg


def home_automation(parameters: dict, player=None) -> str:
    """Tool backend for Jarvis → PC → ESP32 domotics control."""
    raw_device = _normalize_for_matching(str(parameters.get("device", "foco") or "foco"))
    raw_action = _normalize_for_matching(str(parameters.get("action", "toggle") or "toggle"))
    action = ACTION_ALIASES.get(raw_action, raw_action)

    config = _load_domotics_config()
    selected_name = None
    selected_device = None
    for name, device_cfg in config.get("devices", {}).items():
        aliases = {_normalize_for_matching(name)}
        aliases.update(_normalize_for_matching(a) for a in device_cfg.get("aliases", []))
        if raw_device in aliases:
            selected_name = name
            selected_device = device_cfg
            break

    if not selected_device:
        available = ", ".join(sorted(config.get("devices", {}).keys())) or "ninguno"
        return f"Dispositivo no configurado: {raw_device}. Disponibles: {available}."

    command = selected_device.get("commands", {}).get(action)
    if not command:
        return f"Acción no configurada para {selected_name}: {action}."

    ok, response = _send_esp32_command(command, player=player)
    _dispatch_ui(player, "write_log", f"ESP32 <= {command} | ESP32 => {response}")

    if not ok:
        return f"No pude comunicarme con la ESP32. {response}"

    responses = selected_device.get("responses", {})
    for prefix, friendly_text in responses.items():
        if prefix in response:
            return friendly_text
    if "ERR:" in response:
        return f"La ESP32 rechazó el comando: {response}"
    return f"La ESP32 respondió: {response}"


def _get_api_key() -> str:
    try:
        data = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"No existe el archivo de API: {API_CONFIG_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"El archivo de API no contiene JSON válido: {exc}") from exc

    key = str(data.get("gemini_api_key", "")).strip()
    if not key:
        raise RuntimeError("Falta 'gemini_api_key' en config/api_keys.json")
    return key


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        LOGGER.warning("Could not load system prompt: %s", exc)
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


# --- Sleep / wake and adaptive microphone settings ---------------------------
REQUIRE_WAKE_WORD = os.getenv("JARVIS_REQUIRE_WAKE_WORD", "1") != "0"
AWAKE_WINDOW_SECONDS = float(os.getenv("JARVIS_AWAKE_SECONDS", "30"))
POST_RESPONSE_AWAKE_SECONDS = float(os.getenv("JARVIS_FOLLOWUP_SECONDS", "25"))
WAKE_WORDS = (
    "jarvis", "jervis", "yarvis", "jarbis", "charvis", "jarves",
    "arvis", "yervis", "yarves", "jardis",
)

# Adaptive VAD. These can be tuned without editing code.
MIC_MIN_RMS_THRESHOLD = float(os.getenv("JARVIS_MIC_MIN_RMS", "16"))
MIC_MAX_RMS_THRESHOLD = float(os.getenv("JARVIS_MIC_MAX_RMS", "6000"))
MIC_NOISE_MULTIPLIER = float(os.getenv("JARVIS_MIC_NOISE_MULTIPLIER", "1.85"))
MIC_CALIBRATION_SECONDS = float(os.getenv("JARVIS_MIC_CALIBRATION_SECONDS", "1.2"))
MIC_INPUT_DEVICE_RAW = os.getenv("JARVIS_INPUT_DEVICE", "").strip()
MIC_INPUT_DEVICE = (
    int(MIC_INPUT_DEVICE_RAW)
    if MIC_INPUT_DEVICE_RAW.isdigit()
    else (MIC_INPUT_DEVICE_RAW or None)
)
MIC_NOISE_ALPHA = float(os.getenv("JARVIS_MIC_NOISE_ALPHA", "0.035"))
MIC_SPEECH_TRAIL_SECONDS = float(os.getenv("JARVIS_MIC_TRAIL", "1.25"))
MIC_PREROLL_CHUNKS = int(os.getenv("JARVIS_MIC_PREROLL", "5"))

# Never discard model audio. Gemini may deliver chunks faster than real time; a
# small bounded queue can therefore skip words and make speech sound accelerated.
AUDIO_PLAYBACK_QUEUE_CHUNKS = 0  # asyncio.Queue maxsize=0 means unbounded.

OUTPUT_DEVICE_RAW = os.getenv("JARVIS_OUTPUT_DEVICE", "").strip()
OUTPUT_DEVICE = (
    int(OUTPUT_DEVICE_RAW)
    if OUTPUT_DEVICE_RAW.isdigit()
    else (OUTPUT_DEVICE_RAW or None)
)
OUTPUT_SAMPLE_RATE_RAW = os.getenv("JARVIS_OUTPUT_SAMPLE_RATE", "").strip()

# Experimental Live API features are disabled by default because stale session
# handles and context compression can make preview WebSocket sessions reconnect
# repeatedly. They can still be enabled explicitly from the environment.
ENABLE_SESSION_RESUMPTION = os.getenv("JARVIS_SESSION_RESUMPTION", "0") == "1"
ENABLE_CONTEXT_COMPRESSION = os.getenv("JARVIS_CONTEXT_COMPRESSION", "0") == "1"



def _resolve_output_audio_config(device=None, forced_rate=None) -> tuple[int, str]:
    """Return a stable output rate and a human-readable device name.

    Gemini Live sends 24 kHz PCM. On some Windows/Qt audio paths the hardware
    runs at 44.1/48 kHz and can play 24 kHz bytes at the hardware clock, which
    raises pitch and speed. We open the device at its native rate and resample.
    """
    if forced_rate not in (None, "", 0, "0"):
        forced = int(forced_rate)
        if 8_000 <= forced <= 192_000:
            return forced, f"forced device rate ({forced} Hz)"
    elif OUTPUT_SAMPLE_RATE_RAW.isdigit():
        forced = int(OUTPUT_SAMPLE_RATE_RAW)
        if 8_000 <= forced <= 192_000:
            return forced, f"forced device rate ({forced} Hz)"

    selected_device = OUTPUT_DEVICE if device is None else device
    try:
        if selected_device is None:
            info = sd.query_devices(kind="output")
        else:
            info = sd.query_devices(selected_device, kind="output")
        native_rate = int(round(float(info.get("default_samplerate", 0))))
        name = str(info.get("name", "default output"))
        if 8_000 <= native_rate <= 192_000:
            return native_rate, name
    except Exception:
        LOGGER.debug("Could not query native output rate", exc_info=True)

    return RECEIVE_SAMPLE_RATE, "default output"


def _pcm16_rms(data: bytes) -> float:
    """Return RMS level for 16-bit PCM mono audio bytes."""
    if not data:
        return 0.0
    samples = memoryview(data).cast("h")
    if not samples:
        return 0.0
    total = sum(int(sample) * int(sample) for sample in samples)
    return math.sqrt(total / len(samples))


def _apply_pcm_gain(data: bytes, gain: float) -> bytes:
    """Apply safe digital gain to mono PCM16 without extra dependencies."""
    if not data or abs(float(gain) - 1.0) < 0.001:
        return data
    samples = memoryview(data).cast("h")
    output = bytearray(len(data))
    target = memoryview(output).cast("h")
    multiplier = max(0.0, min(4.0, float(gain)))
    for index, sample in enumerate(samples):
        value = int(int(sample) * multiplier)
        target[index] = max(-32768, min(32767, value))
    return bytes(output)


class AudioReconfigureRequested(RuntimeError):
    pass


def _contains_exception(exc: BaseException, expected_type: type[BaseException]) -> bool:
    if isinstance(exc, expected_type):
        return True
    nested = getattr(exc, "exceptions", None)
    return bool(nested and any(_contains_exception(item, expected_type) for item in nested))


def _normalize_for_matching(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    norm = _normalize_for_matching(text)
    if not norm:
        return False
    return any(re.search(rf"\b{re.escape(_normalize_for_matching(word))}\b", norm) for word in words)


def _has_wake_word(text: str) -> bool:
    return _contains_any(text, WAKE_WORDS)


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "home_automation",
        "description": (
            "Controls ANY configured ESP32 domotics device by its ID, visible name, or alias. "
            "Devices are user-configurable and may be lights, fans, pumps, motors, doors, relays, "
            "sensors, or any other actuator. Never restrict this tool to lamps or lights. "
            "Never claim a device was controlled without calling this tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device": {
                    "type": "STRING",
                    "description": "Configured device ID, visible name, or spoken alias, for example foco, ventilador, bomba, puerta, motor, or sensor"
                },
                "action": {
                    "type": "STRING",
                    "description": "Action: on | off | toggle | status | set | list"
                }
            },
            "required": ["device", "action"]
        }
    },
    {
        "name": "list_home_devices",
        "description": (
            "Lists the currently configured ESP32/domotics devices, including names, aliases, GPIOs, "
            "types, and supported actions. Call this when the user asks what devices exist or when a "
            "spoken device name is unclear."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "run_routine",
        "description": (
            "Runs a configured multi-step routine such as Modo Stream, Modo Estudio, "
            "or any routine created in the NEXUS Control Center. Use this instead of "
            "calling many individual tools when the user requests a known routine."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "routine": {"type": "STRING", "description": "Routine name or alias"},
                "variables": {"type": "STRING", "description": "Optional routine variables as a JSON object string"},
                "asynchronous": {"type": "BOOLEAN", "description": "Run in background"}
            },
            "required": ["routine"]
        }
    },
    {
        "name": "manage_mode",
        "description": (
            "Starts, stops, or checks a persistent JARVIS mode. Modes can run entry/exit "
            "routines and keep monitoring the PC or home while active."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "start | stop | status"},
                "mode": {"type": "STRING", "description": "Mode name or alias"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "media_control",
        "description": (
            "Controls Spotify or generic media playback. Use for a specific song, playlist, "
            "play, pause, next, previous, volume, current track, or saving the current track."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | play_track | play_playlist | play | pause | next | previous | volume | save | play_pause"},
                "query": {"type": "STRING", "description": "Song search"},
                "track": {"type": "STRING", "description": "Song name"},
                "playlist": {"type": "STRING", "description": "Playlist name"},
                "volume": {"type": "INTEGER", "description": "Spotify volume 0-100"},
                "device": {"type": "STRING", "description": "Preferred Spotify device"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "obs_control",
        "description": (
            "Controls OBS Studio through OBS WebSocket: status, open, change scene, "
            "start/stop recording, and start/stop streaming. Starting or stopping a live "
            "stream must only happen after explicit user confirmation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | open | set_scene | start_recording | stop_recording | start_stream | stop_stream"},
                "scene": {"type": "STRING", "description": "OBS scene name"},
                "confirmed": {"type": "BOOLEAN", "description": "True only after explicit confirmation"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "pc_status",
        "description": "Returns current CPU, RAM, disk, battery, process count, and top processes.",
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "email_center",
        "description": "Reads and manages Gmail: status, unread, search, read, or mark_read.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | unread | search | read | mark_read"},
                "query": {"type": "STRING", "description": "Gmail search query"},
                "limit": {"type": "INTEGER", "description": "Maximum messages"},
                "message_id": {"type": "STRING", "description": "Gmail message ID"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "notification_center",
        "description": "Lists, reads, or creates JARVIS/Windows notifications.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list | read | windows | emit"},
                "limit": {"type": "INTEGER"},
                "title": {"type": "STRING"},
                "message": {"type": "STRING"},
                "priority": {"type": "STRING"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
]


class JarvisTaskError(RuntimeError):
    """Identifies which concurrent JARVIS task actually failed."""

    def __init__(self, task_name: str, original: BaseException):
        self.task_name = task_name
        self.original = original
        super().__init__(f"{task_name}: {type(original).__name__}: {original}")


def _exception_leaf_messages(exc: BaseException) -> list[str]:
    """Flatten ExceptionGroup so the UI shows the real sub-exception."""
    children = getattr(exc, "exceptions", None)
    if children:
        messages: list[str] = []
        for child in children:
            messages.extend(_exception_leaf_messages(child))
        return messages
    return [f"{type(exc).__name__}: {exc}"]


def _extract_live_audio_chunks(response) -> list[bytes]:
    """Extract only PCM inline_data from a Live API server message.

    Avoid response.data: recent SDK versions warn when a response also contains
    thought/text parts. Google documents model_turn.parts[].inline_data as the
    canonical path for Live audio.
    """
    chunks: list[bytes] = []
    server_content = getattr(response, "server_content", None)
    model_turn = getattr(server_content, "model_turn", None) if server_content else None
    parts = getattr(model_turn, "parts", None) or []
    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        data = getattr(inline_data, "data", None) if inline_data else None
        if not data:
            continue
        mime_type = str(getattr(inline_data, "mime_type", "") or "").lower()
        if mime_type and not mime_type.startswith("audio/"):
            continue
        chunks.append(bytes(data))
    return chunks


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui = ui
        self.session = None
        self.audio_in_queue: asyncio.Queue | None = None
        self.out_queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self._discard_audio_until = 0.0
        self._ignore_audio_until_turn_complete = False
        self._last_interrupt_t = 0.0
        self._sleep_lock = threading.Lock()
        self._awake_until = 0.0
        self._last_mic_activity = 0.0
        self._current_turn_authorized = False
        self._turn_done_event: asyncio.Event | None = None
        self._pending_text_commands: deque[str] = deque(maxlen=8)
        self._session_handle: str | None = None
        self._audio_restart_event: asyncio.Event | None = None
        self._last_mic_rms = 0.0
        self._input_device_name = "not opened"

        # Adaptive VAD state. Values are replaced from config/audio.json.
        self._audio_settings: dict = {}
        self._mic_input_device = MIC_INPUT_DEVICE
        self._output_device = OUTPUT_DEVICE
        self._mic_gain = 1.0
        self._vad_enabled = True
        self._mic_min_rms = MIC_MIN_RMS_THRESHOLD
        self._mic_max_rms = MIC_MAX_RMS_THRESHOLD
        self._mic_noise_multiplier = MIC_NOISE_MULTIPLIER
        self._mic_calibration_seconds = MIC_CALIBRATION_SECONDS
        self._mic_noise_alpha = MIC_NOISE_ALPHA
        self._mic_speech_trail_seconds = MIC_SPEECH_TRAIL_SECONDS
        self._mic_preroll_chunks = MIC_PREROLL_CHUNKS
        self._forced_output_rate = None
        self._noise_floor = max(1.0, self._mic_min_rms / self._mic_noise_multiplier)
        self._mic_speech_active = False
        self._mic_preroll: deque[bytes] = deque(maxlen=max(1, self._mic_preroll_chunks))
        self._mic_calibrating = False
        self._mic_calibration_until = 0.0
        self._mic_calibration_samples: deque[float] = deque(maxlen=128)
        self._output_sample_rate = RECEIVE_SAMPLE_RATE
        self._output_device_name = "not opened"
        self._audio_resampling = False

        # UI updates from asyncio/audio/serial threads are queued and drained
        # by the GUI event loop.  Tk exposes root.after(); the PyQt UI provides
        # the same method through _RootShim.  A direct-dispatch fallback keeps
        # JARVIS compatible with older/custom UI wrappers.
        self._ui_thread_id = threading.get_ident()
        self._ui_queue: queue.Queue[tuple[str, tuple]] = queue.Queue(maxsize=500)
        self._ui_scheduler = getattr(getattr(self.ui, "root", None), "after", None)
        self._ui_queue_enabled = callable(self._ui_scheduler)
        setattr(self.ui, "_jarvis_dispatch", self._ui_call)
        if self._ui_queue_enabled:
            self._schedule_ui_drain()
        else:
            LOGGER.warning(
                "UI root has no after(); using direct UI dispatch. "
                "This is safe for the bundled PyQt signal-based UI."
            )

        self.ui.on_text_command = self._on_text_command
        if hasattr(self.ui, "on_interrupt_command"):
            self.ui.on_interrupt_command = self.interrupt
        if hasattr(self.ui, "on_esp32_connect"):
            self.ui.on_esp32_connect = self._on_esp32_connect
        if hasattr(self.ui, "on_esp32_refresh_ports"):
            self.ui.on_esp32_refresh_ports = self._on_esp32_refresh_ports

        # NEXUS orchestration core. The legacy serial controller is retained so
        # current ESP32 firmware keeps working while new nodes use JSON config.
        self.platform = MarkPlatform(
            BASE_DIR,
            ui=self.ui,
            legacy_home_controller=lambda params: home_automation(params, player=self.ui),
        )
        self.platform.audio.bind_runtime(
            apply_callback=self._on_audio_settings_changed,
            calibrate_callback=self._request_mic_calibration,
            status_callback=self._audio_runtime_status,
        )
        self._prepare_audio_runtime()
        if hasattr(self.ui, "attach_platform"):
            self.ui.attach_platform(self.platform)

        self._ui_call("update_esp32_ports", _list_esp32_ports(), ESP32_PORT)
        self._ui_call("set_esp32_status", "UNKNOWN", ESP32_PORT, "sin verificar")

    def _prepare_audio_runtime(self) -> None:
        settings = self.platform.audio.load()
        self._audio_settings = settings
        self._mic_input_device = settings.get("input_device")
        self._output_device = settings.get("output_device")
        self._mic_gain = float(settings.get("input_gain", 1.2))
        self._vad_enabled = bool(settings.get("vad_enabled", True))
        self._mic_min_rms = float(settings.get("min_rms", 12.0))
        self._mic_max_rms = float(settings.get("max_rms", 6000.0))
        sensitivity = max(1, min(100, int(settings.get("sensitivity", 82))))
        # Higher sensitivity lowers the threshold multiplier.
        self._mic_noise_multiplier = max(0.75, 3.2 - (2.4 * sensitivity / 100.0))
        self._mic_calibration_seconds = float(settings.get("calibration_seconds", 1.2))
        self._mic_noise_alpha = MIC_NOISE_ALPHA
        self._mic_speech_trail_seconds = float(settings.get("speech_trail_seconds", 1.25))
        self._mic_preroll_chunks = int(settings.get("preroll_chunks", 6))
        self._forced_output_rate = settings.get("output_sample_rate")
        self._noise_floor = max(1.0, self._mic_min_rms / max(0.1, self._mic_noise_multiplier))
        self._mic_speech_active = False
        self._mic_preroll = deque(maxlen=max(1, self._mic_preroll_chunks))
        self._mic_calibration_samples.clear()

    def _on_audio_settings_changed(self, _settings: dict) -> None:
        self._ui_log("SYS: Configuración de audio guardada; reiniciando audio...")
        if self._loop and self._audio_restart_event:
            try:
                self._loop.call_soon_threadsafe(self._audio_restart_event.set)
            except RuntimeError:
                pass
        else:
            self._prepare_audio_runtime()

    def _request_mic_calibration(self) -> None:
        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._start_mic_calibration)
                return
            except RuntimeError:
                pass
        self._start_mic_calibration()

    def _audio_runtime_status(self) -> dict:
        return {
            "input_device": self._mic_input_device,
            "output_device": self._output_device,
            "input_device_name": self._input_device_name,
            "output_device_name": self._output_device_name,
            "noise_floor": float(self._noise_floor),
            "threshold": float(self._current_mic_threshold()),
            "rms": float(self._last_mic_rms),
            "vad_enabled": bool(self._vad_enabled),
            "gain": float(self._mic_gain),
            "sample_rate": int(self._output_sample_rate),
        }

    async def _audio_restart_watchdog(self) -> None:
        if self._audio_restart_event is None:
            return
        await self._audio_restart_event.wait()
        raise AudioReconfigureRequested("audio settings changed")

    def _ui_call_direct(self, method: str, *args) -> None:
        fn = getattr(self.ui, method, None)
        if callable(fn):
            try:
                fn(*args)
            except Exception:
                LOGGER.debug("UI call failed: %s", method, exc_info=True)

    def _schedule_ui_drain(self) -> None:
        if not self._ui_queue_enabled or not callable(self._ui_scheduler):
            return
        try:
            self._ui_scheduler(25, self._drain_ui_queue)
        except Exception:
            LOGGER.warning(
                "Could not schedule UI queue; switching to direct dispatch.",
                exc_info=True,
            )
            self._ui_queue_enabled = False

    def _ui_call(self, method: str, *args) -> None:
        if (
            not self._ui_queue_enabled
            or threading.get_ident() == self._ui_thread_id
        ):
            self._ui_call_direct(method, *args)
            return

        item = (method, args)
        try:
            self._ui_queue.put_nowait(item)
        except queue.Full:
            try:
                self._ui_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._ui_queue.put_nowait(item)
            except queue.Full:
                pass

    def _drain_ui_queue(self) -> None:
        processed = 0
        while processed < 100:
            try:
                method, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            fn = getattr(self.ui, method, None)
            if callable(fn):
                try:
                    fn(*args)
                except Exception:
                    LOGGER.debug("Queued UI call failed: %s", method, exc_info=True)
            processed += 1
        self._schedule_ui_drain()

    def _ui_log(self, message: str) -> None:
        LOGGER.info(message)
        self._ui_call("write_log", message)

    def _ui_state(self, state: str) -> None:
        self._ui_call("set_state", state)

    def _current_mic_threshold(self) -> float:
        return max(
            self._mic_min_rms,
            min(self._mic_max_rms, self._noise_floor * self._mic_noise_multiplier),
        )

    def _start_mic_calibration(self) -> None:
        self._mic_calibration_samples.clear()
        self._mic_calibrating = True
        self._mic_calibration_until = time.monotonic() + max(
            0.25, self._mic_calibration_seconds
        )
        self._mic_speech_active = False
        self._mic_preroll.clear()
        self._ui_log("SYS: Calibrando ruido ambiente del micrófono...")

    def _finish_mic_calibration(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self._mic_calibrating:
            return
        samples = sorted(self._mic_calibration_samples)
        if samples:
            # Use a lower percentile so speaking, keyboard hits, or a startup
            # notification cannot become the permanent ambient-noise baseline.
            index = min(len(samples) - 1, int(len(samples) * 0.35))
            self._noise_floor = max(1.0, samples[index])
        self._mic_calibrating = False
        threshold = self._current_mic_threshold()
        loop.call_soon_threadsafe(
            self._ui_log,
            f"SYS: Micrófono calibrado. Ruido={self._noise_floor:.1f}, "
            f"umbral={threshold:.1f}.",
        )

    def _list_microphones(self) -> list[str]:
        try:
            devices = sd.query_devices()
        except Exception as exc:
            return [f"No se pudieron consultar micrófonos: {exc}"]
        results = []
        for index, device in enumerate(devices):
            try:
                if int(device.get("max_input_channels", 0)) > 0:
                    results.append(f"{index}: {device.get('name', 'Micrófono')}")
            except Exception:
                continue
        return results

    def _handle_local_text_command(self, text: str) -> bool:
        if not text.startswith("/"):
            return False

        command, _, value = text.partition(" ")
        command = command.lower()
        value = value.strip()

        if command in {"/help", "/ayuda"}:
            self._ui_log(
                "SYS: Comandos locales: /status, /ports, /esp32 COMx, /home "
                "dispositivo acción, /routines, /routine nombre, /mode start|stop|status nombre, "
                "/media acción [valor], /obs acción [valor], /pc, /mail, /notifications, "
                "/control, /sleep, /wake, /stop, /mic, /mic calibrate, /mic devices, /audio."
            )
        elif command == "/status":
            self._ui_log(
                f"SYS: state={self._idle_state()} | session={'online' if self.session else 'offline'} "
                f"| ESP32={ESP32_PORT} | mic_threshold={self._current_mic_threshold():.1f} "
                f"| audio={RECEIVE_SAMPLE_RATE}->{self._output_sample_rate}Hz "
                f"| mic={self._input_device_name}"
            )
        elif command == "/ports":
            ports = self._on_esp32_refresh_ports()
            names = ", ".join(p["port"] for p in ports) or "ninguno"
            self._ui_log(f"SYS: Puertos disponibles: {names}")
        elif command == "/esp32":
            if value:
                self._on_esp32_connect(value)
            else:
                self._on_esp32_connect(ESP32_PORT)
        elif command == "/sleep":
            self._force_sleep("local command")
        elif command == "/wake":
            self._wake_for_command("local command")
        elif command == "/stop":
            self.interrupt()
        elif command in {"/home", "/domotica"}:
            parts = value.rsplit(" ", 1)
            if len(parts) != 2:
                self._ui_log("SYS: Uso: /home foco on")
            else:
                device, action = parts
                def worker():
                    action_result = self.platform.execute(
                        "domotics.control", {"device": device, "action": action}
                    )
                    result = action_result.message
                    self._ui_log(f"JARVIS LOCAL: {result}")
                    if self.session:
                        self.speak(result)
                threading.Thread(
                    target=worker, name="LocalDomotics", daemon=True
                ).start()
        elif command in {"/control", "/nexus"}:
            self._ui_call("open_control_center")
        elif command in {"/routines", "/rutinas"}:
            names = ", ".join(r.get("name", r.get("id", "")) for r in self.platform.routines.list())
            self._ui_log(f"NEXUS: Rutinas disponibles: {names or 'ninguna'}")
        elif command in {"/routine", "/rutina"}:
            if not value:
                self._ui_log("SYS: Uso: /routine modo stream")
            else:
                self._run_platform_local(lambda: self.platform.run_routine(value))
        elif command == "/mode":
            parts = value.split(maxsplit=1)
            action = parts[0] if parts else "status"
            mode_name = parts[1] if len(parts) > 1 else ""
            self._run_platform_local(lambda: self.platform.manage_mode(action, mode_name))
        elif command == "/media":
            parts = value.split(maxsplit=1)
            action = parts[0] if parts else "status"
            extra = parts[1] if len(parts) > 1 else ""
            payload = {"action": action}
            if action in {"track", "play_track"}: payload["query"] = extra
            elif action in {"playlist", "play_playlist"}: payload["playlist"] = extra
            elif action == "volume" and extra: payload["volume"] = int(extra)
            self._run_platform_local(lambda: self.platform.tool_call("media_control", payload))
        elif command == "/obs":
            parts = value.split(maxsplit=1)
            action = parts[0] if parts else "status"
            payload = {"action": action}
            if action in {"scene", "set_scene"} and len(parts) > 1: payload["scene"] = parts[1]
            self._run_platform_local(lambda: self.platform.tool_call("obs_control", payload))
        elif command == "/pc":
            self._run_platform_local(lambda: self.platform.execute("pc.status"))
        elif command in {"/mail", "/email", "/correo"}:
            self._run_platform_local(lambda: self.platform.tool_call("email_center", {"action": "unread", "limit": 5}))
        elif command in {"/notifications", "/notificaciones"}:
            self._run_platform_local(lambda: self.platform.tool_call("notification_center", {"action": "list", "limit": 10}))
        elif command == "/audio":
            queue_size = self.audio_in_queue.qsize() if self.audio_in_queue else 0
            self._ui_log(
                f"SYS: Gemini PCM={RECEIVE_SAMPLE_RATE}Hz | "
                f"salida={self._output_sample_rate}Hz | "
                f"dispositivo={self._output_device_name} | "
                f"resampling={self._audio_resampling} | cola={queue_size} chunks"
            )
        elif command == "/mic":
            option = value.lower()
            if option in {"calibrate", "calibrar", "recalibrate", "recalibrar"}:
                self._start_mic_calibration()
            elif option in {"devices", "dispositivos"}:
                microphones = self._list_microphones()
                self._ui_log("SYS: Micrófonos disponibles: " + " | ".join(microphones))
            else:
                self._ui_log(
                    f"SYS: mic device={MIC_INPUT_DEVICE!r}, "
                    f"noise_floor={self._noise_floor:.1f}, "
                    f"threshold={self._current_mic_threshold():.1f}, "
                    f"speech_active={self._mic_speech_active}, "
                    f"calibrating={self._mic_calibrating}"
                )
        else:
            self._ui_log(f"SYS: Comando local desconocido: {command}. Usa /help.")
        return True

    def _run_platform_local(self, operation) -> None:
        def worker():
            try:
                result = operation()
                message = getattr(result, "message", str(result))
                warnings_list = getattr(result, "warnings", []) or []
                if warnings_list:
                    message += " | " + " | ".join(str(w) for w in warnings_list)
                self._ui_log(f"NEXUS: {message}")
                if self.session and message:
                    self.speak(message)
            except Exception as exc:
                self._ui_log(f"ERR: NEXUS — {exc}")
        threading.Thread(target=worker, name="NexusLocal", daemon=True).start()

    def _on_text_command(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        if self._handle_local_text_command(text):
            return

        if not self._loop or not self.session:
            self._pending_text_commands.append(text)
            self._ui_log("SYS: JARVIS está reconectando; comando guardado temporalmente.")
            return

        if REQUIRE_WAKE_WORD and not text.startswith("[") and not _has_wake_word(text):
            text = f"Jarvis, {text}"
        self._wake_for_command("typed command")

        future = asyncio.run_coroutine_threadsafe(self._send_text(text), self._loop)
        future.add_done_callback(self._log_future_error)

    async def _send_text(self, text: str) -> None:
        if not self.session:
            self._pending_text_commands.appendleft(text)
            return
        await self.session.send_client_content(
            turns={"parts": [{"text": text}]},
            turn_complete=True,
        )

    def _log_future_error(self, future) -> None:
        try:
            future.result()
        except Exception as exc:
            self._ui_log(f"ERR: No se pudo enviar el comando: {exc}")

    async def _flush_pending_text_commands(self) -> None:
        while self.session and self._pending_text_commands:
            text = self._pending_text_commands.popleft()
            if REQUIRE_WAKE_WORD and not text.startswith("[") and not _has_wake_word(text):
                text = f"Jarvis, {text}"
            self._wake_for_command("queued typed command")
            await self._send_text(text)

    def _on_esp32_refresh_ports(self):
        ports = _list_esp32_ports()
        self._ui_call("update_esp32_ports", ports, ESP32_PORT)
        return ports

    def _on_esp32_connect(self, port: str):
        msg = _set_esp32_port(port)
        self._ui_log(f"SYS: {msg}")
        self._ui_call("set_esp32_status", "CONNECTING", ESP32_PORT, "probando enlace serial")

        def worker():
            matching = next(
                (node for node in self.platform.esp32.list_nodes()
                 if str(node.get("port", "")).upper() == ESP32_PORT.upper()),
                None,
            )
            if matching and matching.get("protocol") != "legacy":
                action_result = self.platform.esp32.connect(str(matching.get("id")))
                ok, response = action_result.ok, action_result.message
                self._ui_call(
                    "set_esp32_status",
                    "ONLINE" if ok else "DISCONNECTED",
                    ESP32_PORT,
                    response,
                )
            else:
                ok, response = _send_esp32_command(
                    "E", wait_seconds=2.0, player=self.ui, show_connecting=False
                )
            state = "en línea" if ok else "desconectada"
            self._ui_log(f"ESP32: {state} en {ESP32_PORT} — {response}")

        threading.Thread(target=worker, name="ESP32Connect", daemon=True).start()

    def interrupt(self):
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(
            self._manual_interrupt(),
            self._loop
        )

    def _get_speaking(self) -> bool:
        with self._speaking_lock:
            return self._is_speaking

    def _is_awake(self) -> bool:
        with self._sleep_lock:
            return time.monotonic() < self._awake_until

    def _idle_state(self) -> str:
        return "LISTENING" if self._is_awake() else "SLEEPING"

    def _wake_for_command(self, reason: str = "wake word"):
        with self._sleep_lock:
            was_asleep = time.monotonic() >= self._awake_until
            self._awake_until = time.monotonic() + AWAKE_WINDOW_SECONDS
        self._current_turn_authorized = True
        if not self.ui.muted and not self._get_speaking():
            self._ui_state("LISTENING")
        if was_asleep:
            self._ui_log(
                f"SYS: Awake for {int(AWAKE_WINDOW_SECONDS)}s ({reason})."
            )

    def _extend_awake_window(self):
        if self._is_awake():
            with self._sleep_lock:
                self._awake_until = time.monotonic() + AWAKE_WINDOW_SECONDS

    def _refresh_followup_window(self, reason: str = "response finished"):
        """Keep Jarvis awake for a short follow-up after it finishes talking.

        Without this, a long spoken answer can outlive the original wake window,
        so Jarvis returns to sleep before the user can answer.
        """
        if not REQUIRE_WAKE_WORD:
            return
        with self._sleep_lock:
            self._awake_until = time.monotonic() + POST_RESPONSE_AWAKE_SECONDS
        if not self.ui.muted:
            self._ui_state("LISTENING")
        self._ui_log(
            f"SYS: Follow-up window {int(POST_RESPONSE_AWAKE_SECONDS)}s ({reason})."
        )

    def _force_sleep(self, reason: str | None = None):
        with self._sleep_lock:
            already_asleep = time.monotonic() >= self._awake_until
            self._awake_until = 0.0
        self._current_turn_authorized = False
        if not self.ui.muted and not self._get_speaking():
            self._ui_state("SLEEPING")
        if reason and not already_asleep:
            self._ui_log(f"SYS: Sleeping ({reason}).")

    async def _sleep_watchdog(self):
        was_awake = False
        while True:
            await asyncio.sleep(0.25)
            awake = self._is_awake()
            if awake:
                was_awake = True
                continue
            if was_awake:
                was_awake = False
                if not self.ui.muted and not self._get_speaking():
                    self._ui_state("SLEEPING")
                    self._ui_log("SYS: Sleeping. Say 'Jarvis' to wake.")

    def _queue_mic_audio(self, data: bytes):
        if not self.out_queue:
            return
        try:
            if self.out_queue.full():
                # Drop the oldest pending mic chunk instead of letting latency grow.
                try:
                    self.out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            self.out_queue.put_nowait(
                types.Blob(
                    data=data,
                    mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}",
                )
            )
        except asyncio.QueueFull:
            pass

    def _queue_playback_audio(self, data: bytes) -> None:
        """Queue every assistant audio chunk in order; never skip spoken bytes."""
        if not self.audio_in_queue or not data:
            return
        self.audio_in_queue.put_nowait(data)

    async def _clear_audio_queue(self):
        if not self.audio_in_queue:
            return
        while True:
            try:
                self.audio_in_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _send_silent_interrupt(self):
        if not self.session:
            return
        try:
            await self.session.send_client_content(
                turns={
                    "parts": [{
                        "text": (
                            "[INTERRUPT] Stop the current spoken response now. "
                            "Stay silent. The app is returning to sleeping mode; "
                            "wait for a future command that starts with Jarvis."
                        )
                    }]
                },
                turn_complete=True,
            )
        except Exception:
            pass

    async def _interrupt_current_response(self, reason: str = "voice", *, discard_until_turn_complete: bool = False):
        now = time.monotonic()
        if now - self._last_interrupt_t < 0.45:
            return
        self._last_interrupt_t = now
        self._discard_audio_until = max(self._discard_audio_until, now + 0.75)
        self._ignore_audio_until_turn_complete = discard_until_turn_complete
        await self._clear_audio_queue()
        self.set_speaking(False)
        self._ui_log(f"SYS: Interrupted current response ({reason}).")

    async def _manual_interrupt(self):
        await self._interrupt_current_response("manual", discard_until_turn_complete=True)
        await self._send_silent_interrupt()
        self._force_sleep("manual stop")

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self._ui_state("SPEAKING")
        elif not self.ui.muted:
            self._ui_state(self._idle_state())

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        future = asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )
        future.add_done_callback(self._log_future_error)

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self._ui_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()
        wake_protocol = (
            "[SLEEP / WAKE PROTOCOL]\n"
            "Jarvis starts in SLEEPING mode. For spoken microphone input, only answer "
            "or call tools when the command contains the wake word 'Jarvis', or when "
            "the user is already in the short active window after saying Jarvis.\n"
            "If speech is background conversation, noise, or does not seem intended for "
            "Jarvis, stay completely silent: do not answer, do not apologize, and do not call tools.\n"
            "Treat 'Jarvis' only as activation, then answer the remaining command.\n"
            "During the active window, brief follow-up spoken commands may be handled "
            "even if they do not repeat the wake word.\n"
            "Voice barge-in is disabled. Do not stop your response because of a new "
            "spoken command; manual ESC/STOP is handled by the app.\n"
            "Typed UI messages and bracketed internal messages such as [FILE_UPLOADED] "
            "are intentional and may be handled normally.\n"
            "Keep replies short.\n"
        )

        device_catalog = self.platform.esp32.describe_catalog()
        domotica_protocol = (
            "[HOME AUTOMATION / ESP32]\n"
            "The user can create and rename arbitrary devices. Never assume domotics only means lights. "
            "Use home_automation for any configured fan, pump, motor, door, relay, light, sensor, or actuator. "
            "Resolve the user's words using ID, visible name, and aliases from the live catalog below. "
            "Use list_home_devices if the requested name is unclear. Actions: on, off, toggle, status, set, list. "
            "Keep confirmations short and use the configured visible name.\n"
            "[LIVE DEVICE CATALOG]\n" + device_catalog + "\n"
        )

        nexus_protocol = (
            "[NEXUS ROUTINES, MODES AND SERVICES]\n"
            "Use run_routine when the user requests a configured multi-step routine such as mode stream. "
            "Use manage_mode for persistent modes that remain active and monitor the environment. "
            "Use media_control for Spotify, songs, playlists, playback and volume. "
            "Use obs_control for OBS scenes, recording and streaming. Never start or stop a live stream "
            "without explicit confirmation. Use pc_status for computer health, email_center for Gmail, "
            "and notification_center for notification requests. Report partial failures honestly.\n"
        )

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx, wake_protocol, domotica_protocol, nexus_protocol]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        config_kwargs = {
            "response_modalities": ["AUDIO"],
            "output_audio_transcription": {},
            "input_audio_transcription": {},
            "system_instruction": "\n".join(parts),
            "tools": [{"function_declarations": TOOL_DECLARATIONS}],
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        }

        if ENABLE_SESSION_RESUMPTION:
            try:
                if self._session_handle:
                    config_kwargs["session_resumption"] = types.SessionResumptionConfig(
                        handle=self._session_handle
                    )
                else:
                    config_kwargs["session_resumption"] = types.SessionResumptionConfig()
            except Exception:
                LOGGER.debug("Session resumption is unavailable", exc_info=True)

        if ENABLE_CONTEXT_COMPRESSION:
            compression_cls = getattr(types, "ContextWindowCompressionConfig", None)
            sliding_cls = getattr(types, "SlidingWindow", None)
            if compression_cls and sliding_cls:
                try:
                    config_kwargs["context_window_compression"] = compression_cls(
                        sliding_window=sliding_cls()
                    )
                except Exception:
                    LOGGER.debug("Context compression is unavailable", exc_info=True)

        return types.LiveConnectConfig(**config_kwargs)

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        LOGGER.info("Tool call: %s %s", name, args)

        # Final local safety gate: no tool execution while sleeping unless the
        # current spoken turn has been authorized by Jarvis/wake mode. Typed UI
        # commands are sent as intentional client text and remain supported.
        if name != "save_memory" and not self._current_turn_authorized and not self._is_awake():
            self._ui_log(f"SYS: Blocked '{name}' while sleeping.")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ignored_sleeping_no_wake_word", "silent": True}
            )

        self._ui_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                LOGGER.info("Memory saved: %s/%s", category, key)
            if not self.ui.muted:
                self._ui_state(self._idle_state())
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_running_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated. Stay completely silent — vision module will speak directly."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name in {
                "run_routine", "manage_mode", "media_control", "obs_control",
                "pc_status", "email_center", "notification_center"
            }:
                action_result = await loop.run_in_executor(
                    None, lambda: self.platform.tool_call(name, args)
                )
                result = action_result.message
                if action_result.warnings:
                    result += " Advertencias: " + " | ".join(action_result.warnings)

            elif name == "home_automation":
                action_result = await loop.run_in_executor(
                    None, lambda: self.platform.tool_call("home_automation", args)
                )
                result = action_result.message

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shutdown_jarvis":
                self._ui_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    try:
                        self.platform.shutdown()
                    except Exception:
                        LOGGER.debug("NEXUS shutdown cleanup failed", exc_info=True)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            LOGGER.exception("Unhandled operation error")
            self.speak_error(name, e)

        if not self.ui.muted:
            self._ui_state(self._idle_state())

        LOGGER.info("Tool result %s: %s", name, str(result)[:160])
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _esp32_status_watchdog(self):
        await asyncio.sleep(1.0)
        while True:
            try:
                self._ui_call("update_esp32_ports", _list_esp32_ports(), ESP32_PORT)
                matching = next(
                    (node for node in self.platform.esp32.list_nodes()
                     if str(node.get("port", "")).upper() == ESP32_PORT.upper()),
                    None,
                )
                if matching and matching.get("protocol") != "legacy":
                    action_result = await asyncio.to_thread(
                        self.platform.esp32.connect, str(matching.get("id"))
                    )
                    ok, response = action_result.ok, action_result.message
                    self._ui_call(
                        "set_esp32_status",
                        "ONLINE" if ok else "DISCONNECTED",
                        ESP32_PORT,
                        response,
                    )
                else:
                    ok, response = await asyncio.to_thread(
                        _send_esp32_command,
                        "E",
                        0.9,
                        self.ui,
                        show_connecting=False,
                    )
                    if not ok:
                        self._ui_call("set_esp32_status", "DISCONNECTED", ESP32_PORT, response)
            except Exception as exc:
                self._ui_call("set_esp32_status", "DISCONNECTED", ESP32_PORT, str(exc))
                LOGGER.warning("ESP32 watchdog error: %s", exc)
            await asyncio.sleep(max(3.0, ESP32_HEALTH_INTERVAL))

    async def _guard_task(self, task_name: str, coroutine):
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("Concurrent task '%s' failed", task_name)
            self._ui_log(
                f"ERR: Tarea {task_name} — {type(exc).__name__}: {exc}"
            )
            raise JarvisTaskError(task_name, exc) from exc

    async def _send_realtime(self):
        while True:
            audio_blob = await self.out_queue.get()
            # Official Live API format: audio=types.Blob(...).
            await self.session.send_realtime_input(audio=audio_blob)

    async def _listen_audio(self):
        LOGGER.info("Microphone task started")
        loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status):
            if status:
                LOGGER.warning("Audio input status: %s", status)
            if self.ui.muted or self._get_speaking():
                return

            data = _apply_pcm_gain(indata.tobytes(), self._mic_gain)
            now = time.monotonic()
            rms = _pcm16_rms(data)
            self._last_mic_rms = rms

            if not self._vad_enabled:
                loop.call_soon_threadsafe(self._queue_mic_audio, data)
                return

            if self._mic_calibrating:
                if now < self._mic_calibration_until:
                    self._mic_calibration_samples.append(rms)
                    self._mic_preroll.append(data)
                    return
                self._finish_mic_calibration(loop)

            threshold = self._current_mic_threshold()

            # Learn ambient noise only when speech is not active. The ceiling avoids
            # treating an actual voice burst as the new room-noise baseline.
            if not self._mic_speech_active and rms < threshold:
                if rms < max(threshold * 1.4, self._mic_min_rms * 2):
                    self._noise_floor = (
                        (1.0 - self._mic_noise_alpha) * self._noise_floor
                        + self._mic_noise_alpha * max(1.0, rms)
                    )
                self._mic_preroll.append(data)
                return

            if rms >= threshold:
                if not self._mic_speech_active:
                    self._mic_speech_active = True
                    while self._mic_preroll:
                        loop.call_soon_threadsafe(
                            self._queue_mic_audio, self._mic_preroll.popleft()
                        )
                self._last_mic_activity = now
                loop.call_soon_threadsafe(self._queue_mic_audio, data)
                return

            if self._mic_speech_active and (
                now - self._last_mic_activity
            ) < self._mic_speech_trail_seconds:
                loop.call_soon_threadsafe(self._queue_mic_audio, data)
                return

            self._mic_speech_active = False
            self._mic_preroll.clear()
            self._mic_preroll.append(data)

        try:
            self._start_mic_calibration()
            try:
                input_info = sd.query_devices(self._mic_input_device, kind="input") if self._mic_input_device is not None else sd.query_devices(kind="input")
                self._input_device_name = str(input_info.get("name", "default input"))
            except Exception:
                self._input_device_name = str(self._mic_input_device if self._mic_input_device is not None else "default input")
            with sd.InputStream(
                device=self._mic_input_device,
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                latency="low",
                callback=callback,
            ):
                self._ui_log(
                    f"SYS: Entrada de audio abierta"
                    f" en {self._input_device_name}."
                )
                while True:
                    await asyncio.sleep(0.2)
        except Exception as exc:
            LOGGER.exception("Microphone failed")
            self._ui_log(f"ERR: Micrófono — {exc}")
            raise

    async def _receive_audio(self):
        LOGGER.info("Receive task started")
        out_buf, in_buf = [], []
        pending_audio: deque[bytes] = deque(maxlen=160)

        def flush_pending_audio():
            if not self.audio_in_queue:
                pending_audio.clear()
                return
            if self._turn_done_event and self._turn_done_event.is_set():
                self._turn_done_event.clear()
            while pending_audio:
                self._queue_playback_audio(pending_audio.popleft())

        try:
            while True:
                async for response in self.session.receive():

                    resumption = getattr(response, "session_resumption_update", None)
                    if (
                        ENABLE_SESSION_RESUMPTION
                        and resumption
                        and getattr(resumption, "resumable", False)
                        and getattr(resumption, "new_handle", None)
                    ):
                        self._session_handle = resumption.new_handle

                    go_away = getattr(response, "go_away", None)
                    if go_away:
                        time_left = getattr(go_away, "time_left", None)
                        self._ui_log(
                            f"SYS: El servidor renovará la conexión"
                            f"{f' en {time_left}' if time_left else ''}."
                        )

                    for audio_chunk in _extract_live_audio_chunks(response):
                        should_discard_audio = (
                            self._ignore_audio_until_turn_complete
                            or time.monotonic() < self._discard_audio_until
                        )
                        if should_discard_audio:
                            continue
                        if self._current_turn_authorized or self._is_awake():
                            flush_pending_audio()
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            self._queue_playback_audio(audio_chunk)
                        else:
                            # Sleeping mode: buffer briefly in case the input
                            # transcript later proves this turn had "Jarvis".
                            pending_audio.append(audio_chunk)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)
                                if _has_wake_word(txt):
                                    self._wake_for_command("wake word")
                                    flush_pending_audio()
                                elif self._is_awake():
                                    self._current_turn_authorized = True
                                    self._extend_awake_window()
                                    flush_pending_audio()

                        if sc.turn_complete:
                            self._ignore_audio_until_turn_complete = False
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            full_out = " ".join(out_buf).strip()
                            authorized = self._current_turn_authorized or (full_in and _has_wake_word(full_in))

                            if authorized:
                                if full_in:
                                    self._ui_log(f"You: {full_in}")
                                    self._extend_awake_window()
                                if full_out:
                                    self._ui_log(f"Jarvis: {full_out}")
                            else:
                                # Do not display/transcribe background speech in the UI.
                                pending_audio.clear()

                            in_buf = []
                            out_buf = []
                            pending_audio.clear()
                            self._current_turn_authorized = False

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            LOGGER.info("Function requested: %s", fc.name)
                            if not self._current_turn_authorized and not self._is_awake():
                                self._ui_log(f"SYS: Ignored tool '{fc.name}' while sleeping.")
                                fr = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": "ignored_sleeping_no_wake_word", "silent": True},
                                )
                            else:
                                fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            LOGGER.exception("Unhandled operation error")
            raise

    async def _play_audio(self):
        LOGGER.info("Playback task started")

        output_rate, device_name = _resolve_output_audio_config(self._output_device, self._forced_output_rate)
        if output_rate != RECEIVE_SAMPLE_RATE and _audioop is None:
            # Safe fallback for Python versions without audioop. It is better to
            # request 24 kHz than to play unconverted samples at the wrong speed.
            LOGGER.warning(
                "Native output is %s Hz but no PCM resampler is available; "
                "falling back to %s Hz.",
                output_rate,
                RECEIVE_SAMPLE_RATE,
            )
            output_rate = RECEIVE_SAMPLE_RATE

        self._output_sample_rate = output_rate
        self._output_device_name = device_name
        self._audio_resampling = output_rate != RECEIVE_SAMPLE_RATE
        self._ui_log(
            f"SYS: Audio de salida: Gemini {RECEIVE_SAMPLE_RATE}Hz -> "
            f"{output_rate}Hz ({device_name})"
        )

        stream = sd.RawOutputStream(
            device=self._output_device,
            samplerate=output_rate,
            channels=CHANNELS,
            dtype="int16",
            blocksize=0,
            latency="low",
        )
        stream.start()
        rate_state = None

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        was_speaking = self._get_speaking()
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                        if was_speaking:
                            self._refresh_followup_window()
                    continue

                if not chunk:
                    continue
                if len(chunk) % 2:
                    chunk = chunk[:-1]
                if not chunk:
                    continue

                if output_rate != RECEIVE_SAMPLE_RATE:
                    chunk, rate_state = _audioop.ratecv(
                        chunk,
                        2,  # 16-bit samples
                        CHANNELS,
                        RECEIVE_SAMPLE_RATE,
                        output_rate,
                        rate_state,
                    )

                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception:
            LOGGER.exception("Playback failed")
            raise
        finally:
            self.set_speaking(False)
            self._audio_resampling = False
            try:
                stream.stop()
            finally:
                stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"},
        )
        reconnect_delay = 1.0

        while True:
            try:
                LOGGER.info("Connecting to Gemini Live model %s", LIVE_MODEL)
                self._ui_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session
                    self._loop = asyncio.get_running_loop()
                    self._prepare_audio_runtime()
                    self._audio_restart_event = asyncio.Event()
                    # Unbounded by design: dropping assistant PCM chunks makes
                    # speech skip forward and sound accelerated/garbled.
                    self.audio_in_queue = asyncio.Queue(
                        maxsize=AUDIO_PLAYBACK_QUEUE_CHUNKS
                    )
                    self.out_queue = asyncio.Queue(maxsize=12)
                    self._turn_done_event = asyncio.Event()
                    reconnect_delay = 1.0

                    self._force_sleep()
                    self._ui_log(
                        "SYS: JARVIS online. Sleeping — di 'Jarvis' para activarlo."
                    )
                    await self._flush_pending_text_commands()

                    tg.create_task(
                        self._guard_task("send-realtime", self._send_realtime()),
                        name="send-realtime",
                    )
                    tg.create_task(
                        self._guard_task("listen-audio", self._listen_audio()),
                        name="listen-audio",
                    )
                    tg.create_task(
                        self._guard_task("receive-audio", self._receive_audio()),
                        name="receive-audio",
                    )
                    tg.create_task(
                        self._guard_task("play-audio", self._play_audio()),
                        name="play-audio",
                    )
                    tg.create_task(
                        self._guard_task("sleep-watchdog", self._sleep_watchdog()),
                        name="sleep-watchdog",
                    )
                    tg.create_task(
                        self._guard_task("esp32-watchdog", self._esp32_status_watchdog()),
                        name="esp32-watchdog",
                    )
                    tg.create_task(
                        self._audio_restart_watchdog(),
                        name="audio-restart",
                    )

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if _contains_exception(exc, AudioReconfigureRequested):
                    LOGGER.info("Restarting Live session to apply audio settings")
                    self._ui_log("SYS: Reiniciando audio con la nueva configuración...")
                    reconnect_delay = 0.2
                else:
                    LOGGER.exception("Live session failed")
                    details = " | ".join(_exception_leaf_messages(exc))
                    self._ui_log(f"ERR: Sesión de JARVIS — {details}")
                    # A handle captured from a broken preview session can poison the
                    # next connection. Never reuse it after an abnormal disconnect.
                    self._session_handle = None
            finally:
                self.session = None
                self.audio_in_queue = None
                self.out_queue = None
                self._turn_done_event = None
                self._audio_restart_event = None
                self.set_speaking(False)

            self._ui_state("THINKING")
            self._ui_log(
                f"SYS: Reconectando en {reconnect_delay:.0f}s..."
            )
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(30.0, reconnect_delay * 2.0)

def main():
    ui = JarvisUI("face.png")
    jarvis = JarvisLive(ui)

    def runner():
        try:
            ui.wait_for_api_key()
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            LOGGER.info("Shutting down by keyboard interrupt")
        except Exception:
            LOGGER.exception("Fatal runner error")
            jarvis._ui_log("ERR: JARVIS no pudo iniciar. Revisa logs/jarvis.log.")

    threading.Thread(target=runner, name="JarvisAsync", daemon=True).start()
    ui.root.mainloop()
    try:
        jarvis.platform.shutdown()
    except Exception:
        LOGGER.debug("NEXUS shutdown cleanup failed", exc_info=True)
    _close_esp32()


if __name__ == "__main__":
    main()
