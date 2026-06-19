from __future__ import annotations

import asyncio
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable

from google import genai
from google.genai import types

from prp.core.text import normalize_voice_text


TOOL_DECLARATIONS = [
    {
        "name": "home_automation",
        "description": "Controla un dispositivo domótico configurado en una ESP32. Siempre úsala para focos, luces, relés, ventiladores y sensores.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device": {"type": "STRING", "description": "Nombre o alias del dispositivo, por ejemplo foco o luz."},
                "action": {"type": "STRING", "description": "on, off, toggle, status o set."},
                "value": {"type": "NUMBER", "description": "Nivel opcional para PWM."},
            },
            "required": ["device", "action"],
        },
    },
    {
        "name": "media_control",
        "description": "Controla Spotify o multimedia: canciones, playlists, pausa, siguiente, volumen y estado.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "smart_play, status, play_track, play_playlist, play_artist, play_album, another_by_artist, play, pause, next, previous, volume, save, context o list_playlists."},
                "query": {"type": "STRING", "description": "Nombre o búsqueda musical."},
                "track": {"type": "STRING", "description": "Nombre de canción."},
                "playlist": {"type": "STRING", "description": "Nombre de playlist."},
                "artist": {"type": "STRING", "description": "Nombre del artista."},
                "album": {"type": "STRING", "description": "Nombre del álbum."},
                "alias": {"type": "STRING", "description": "Alias personal, por ejemplo stream o estudio."},
                "target_type": {"type": "STRING", "description": "auto, alias, track, playlist, artist o album."},
                "relation": {"type": "STRING", "description": "same_artist, return_playlist u otra referencia contextual."},
                "volume": {"type": "INTEGER", "description": "Volumen de 0 a 100."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "obs_control",
        "description": "Controla OBS Studio: abrir, consultar, cambiar escena, grabar o transmitir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status, open, scene, start_recording, stop_recording, start_stream o stop_stream."},
                "scene": {"type": "STRING", "description": "Nombre exacto de la escena."},
                "confirmed": {"type": "BOOLEAN", "description": "Confirmación explícita para acciones críticas."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "run_routine",
        "description": "Ejecuta una rutina configurable como Modo Stream o Modo Estudio.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "routine": {"type": "STRING"},
                "variables": {"type": "STRING", "description": "JSON opcional con variables."},
                "asynchronous": {"type": "BOOLEAN"},
            },
            "required": ["routine"],
        },
    },
    {
        "name": "manage_mode",
        "description": "Activa, detiene o consulta un modo persistente.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"action": {"type": "STRING"}, "mode": {"type": "STRING"}},
            "required": ["action", "mode"],
        },
    },
    {
        "name": "pc_status",
        "description": "Consulta CPU, RAM, discos, batería y estado general de la PC.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "task_manager",
        "description": "Crea, lista, completa o elimina tareas locales.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"}, "title": {"type": "STRING"}, "id": {"type": "STRING"},
                "notes": {"type": "STRING"}, "due": {"type": "STRING"}, "priority": {"type": "STRING"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "email_center",
        "description": "Consulta correos de Gmail: estado, no leídos, buscar, leer o marcar leído.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"action": {"type": "STRING"}, "query": {"type": "STRING"}, "id": {"type": "STRING"}},
            "required": ["action"],
        },
    },
]



_normalize = normalize_voice_text

class GeminiLiveService:
    """Owns the only Gemini Live session and the sleep/wake state machine."""

    def __init__(
        self,
        config_manager,
        platform,
        audio,
        events,
        *,
        on_state: Callable[[str], None],
        on_log: Callable[[str], None],
        on_countdown: Callable[[float], None],
    ):
        self.config_manager = config_manager
        self.platform = platform
        self.audio = audio
        self.events = events
        self.on_state = on_state
        self.on_log = on_log
        self.on_countdown = on_countdown

        self.loop: asyncio.AbstractEventLoop | None = None
        self.session = None
        self.input_queue: asyncio.Queue | None = None
        self.output_queue: asyncio.Queue | None = None
        self.turn_done: asyncio.Event | None = None
        self._stop = threading.Event()
        self._state = "OFFLINE"
        self._state_lock = threading.RLock()
        self._awake_until = 0.0
        self._current_turn_authorized = False
        self._ignore_output_until_turn_complete = False
        self._connected = False
        self._last_key_notice = 0.0

    @property
    def connected(self) -> bool:
        return self._connected and self.session is not None

    def stop(self) -> None:
        self._stop.set()
        loop = self.loop
        if loop and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(lambda: None)
            except RuntimeError:
                pass

    def enqueue_audio_threadsafe(self, data: bytes) -> None:
        loop = self.loop
        queue = self.input_queue
        if not self.connected or loop is None or queue is None or loop.is_closed():
            return

        def put() -> None:
            if self.input_queue is None:
                return
            try:
                if self.input_queue.full():
                    self.input_queue.get_nowait()
                self.input_queue.put_nowait(data)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

        try:
            loop.call_soon_threadsafe(put)
        except RuntimeError:
            pass

    def send_text_threadsafe(self, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send_text(text), loop)
        except RuntimeError:
            pass

    def interrupt_threadsafe(self) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._interrupt(), loop)
        except RuntimeError:
            pass

    async def _send_text(self, text: str) -> None:
        if not self.connected:
            self.on_log("SYS: JARVIS todavía no está conectado a Gemini.")
            return
        self._wake("orden escrita")
        self._set_state("THINKING")
        await self.session.send_realtime_input(text=text)

    async def _interrupt(self) -> None:
        self._ignore_output_until_turn_complete = True
        await self._clear_output_queue()
        self.audio.set_speaking(False)
        self._force_sleep("interrupción manual")
        try:
            if self.connected:
                await self.session.send_realtime_input(text="[INTERRUPT] Detén la respuesta actual y permanece en silencio.")
        except Exception:
            pass

    def _settings(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        app = self.config_manager.app()
        return app.get("assistant", {}), app.get("gemini", {}), app.get("audio", {})

    def _wake_words(self) -> tuple[str, ...]:
        assistant, _, _ = self._settings()
        return tuple(_normalize(word) for word in assistant.get("wake_words", ["jarvis"]) if word)

    def _has_wake_word(self, text: str) -> bool:
        normalized = _normalize(text)
        return any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in self._wake_words())

    def _is_awake(self) -> bool:
        return time.monotonic() < self._awake_until

    def _wake(self, reason: str) -> None:
        assistant, _, _ = self._settings()
        seconds = max(5, int(assistant.get("followup_seconds", 30)))
        was_asleep = not self._is_awake()
        self._awake_until = time.monotonic() + seconds
        self._current_turn_authorized = True
        self._set_state("LISTENING")
        if was_asleep:
            self.on_log(f"SYS: JARVIS activo durante {seconds}s ({reason}).")

    def _refresh_followup(self) -> None:
        assistant, _, _ = self._settings()
        seconds = max(5, int(assistant.get("followup_seconds", 30)))
        self._awake_until = time.monotonic() + seconds
        self._set_state("LISTENING")
        self.on_log(f"SYS: Ventana de seguimiento: {seconds}s.")

    def _force_sleep(self, reason: str = "") -> None:
        self._awake_until = 0.0
        self._current_turn_authorized = False
        self.on_countdown(0.0)
        self._set_state("SLEEPING")
        if reason:
            self.on_log(f"SYS: STANDBY ({reason}). Di 'Jarvis' para activarlo.")

    def _set_state(self, state: str) -> None:
        with self._state_lock:
            if self._state == state:
                return
            self._state = state
        self.on_state(state)
        self.events.publish("assistant.state", {"state": state}, "gemini")

    async def run_forever(self) -> None:
        self.loop = asyncio.get_running_loop()
        backoff = 1.0
        while not self._stop.is_set():
            key = self.config_manager.api_key()
            if not key:
                self._connected = False
                self._set_state("OFFLINE")
                now = time.monotonic()
                if now - self._last_key_notice > 8:
                    self._last_key_notice = now
                    self.on_log("SYS: Falta la API key de Gemini. Configúrala desde la pantalla inicial.")
                await asyncio.sleep(1.0)
                continue
            try:
                self._set_state("CONNECTING")
                await self._run_session(key)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self.session = None
                self.audio.set_speaking(False)
                self._set_state("OFFLINE")
                self.on_log(f"ERR: Sesión Gemini — {type(exc).__name__}: {exc}")
                self.events.publish("gemini.session.error", {"type": type(exc).__name__, "message": str(exc)}, "gemini")
                if self._stop.is_set():
                    break
                self.on_log(f"SYS: Reconectando en {backoff:.0f}s...")
                await asyncio.sleep(backoff)
                backoff = min(20.0, backoff * 1.8)

    async def _run_session(self, api_key: str) -> None:
        assistant, gemini_cfg, _ = self._settings()
        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        model = str(gemini_cfg.get("model", "gemini-3.1-flash-live-preview"))
        voice = str(gemini_cfg.get("voice", "Charon"))
        now = datetime.now().strftime("%A, %d de %B de %Y, %H:%M")
        prompt = (
            "Eres JARVIS, el asistente de Pavo's Robotic Projects. Responde en español, breve y natural.\n"
            "PROTOCOLO DE ACTIVACIÓN: cuando la entrada provenga del micrófono y JARVIS esté en standby, "
            "solo responde o llama herramientas si la frase contiene la palabra Jarvis. Durante la ventana de seguimiento "
            "puedes aceptar frases breves sin repetir Jarvis. El texto escrito siempre es intencional.\n"
            "DOMÓTICA: para prender, apagar, alternar o consultar focos, luces, relés o sensores, usa home_automation. "
            "Nunca afirmes que controlaste un dispositivo sin recibir un resultado exitoso de la herramienta.\n"
            "MULTIMEDIA: usa media_control con smart_play y especifica target_type cuando el usuario diga canción, playlist, artista, álbum o alias. Conserva referencias como otra de ese artista.\n"
            "RUTINAS: usa run_routine para modos complejos como stream o estudio.\n"
            f"Fecha y hora local: {now}. Nombre preferido del usuario: Pavo."
        )
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription={},
            output_audio_transcription={},
            system_instruction=prompt,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        )
        async with client.aio.live.connect(model=model, config=config) as session:
            self.session = session
            self.input_queue = asyncio.Queue(maxsize=20)
            self.output_queue = asyncio.Queue()
            self.turn_done = asyncio.Event()
            self._connected = True
            self._force_sleep()
            self.on_log("SYS: JARVIS online. STANDBY — di 'Jarvis' con voz normal.")
            self.events.publish("gemini.session.online", {"model": model}, "gemini")
            async with asyncio.TaskGroup() as group:
                group.create_task(self._send_audio_loop(), name="send-audio")
                group.create_task(self._receive_loop(), name="receive")
                group.create_task(self._playback_loop(), name="playback")
                group.create_task(self._standby_watchdog(), name="standby")

    async def _send_audio_loop(self) -> None:
        while self.connected and not self._stop.is_set():
            data = await self.input_queue.get()
            await self.session.send_realtime_input(
                audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
            )

    async def _receive_loop(self) -> None:
        input_parts: list[str] = []
        output_parts: list[str] = []
        pending_audio: list[bytes] = []

        async def flush_pending() -> None:
            while pending_audio:
                await self.output_queue.put(pending_audio.pop(0))

        async for response in self.session.receive():
            sc = getattr(response, "server_content", None)
            if sc:
                input_tx = getattr(sc, "input_transcription", None)
                if input_tx and getattr(input_tx, "text", None):
                    text = str(input_tx.text).strip()
                    if text:
                        input_parts.append(text)
                        if self._has_wake_word(text):
                            self._wake("wake word")
                            await flush_pending()
                        elif self._is_awake():
                            self._current_turn_authorized = True
                            self._set_state("THINKING")
                            await flush_pending()

                output_tx = getattr(sc, "output_transcription", None)
                if output_tx and getattr(output_tx, "text", None):
                    text = str(output_tx.text).strip()
                    if text:
                        output_parts.append(text)

                model_turn = getattr(sc, "model_turn", None)
                if model_turn:
                    for part in getattr(model_turn, "parts", []) or []:
                        inline = getattr(part, "inline_data", None)
                        data = getattr(inline, "data", None) if inline else None
                        if data:
                            if self._ignore_output_until_turn_complete:
                                continue
                            if self._current_turn_authorized or self._is_awake():
                                await flush_pending()
                                await self.output_queue.put(bytes(data))
                            else:
                                pending_audio.append(bytes(data))
                                if len(pending_audio) > 220:
                                    pending_audio.pop(0)

                if getattr(sc, "turn_complete", False):
                    self._ignore_output_until_turn_complete = False
                    if self.turn_done:
                        self.turn_done.set()
                    full_input = " ".join(input_parts).strip()
                    full_output = " ".join(output_parts).strip()
                    authorized = self._current_turn_authorized or (full_input and self._has_wake_word(full_input))
                    if authorized:
                        if full_input:
                            self.on_log(f"Pavo: {full_input}")
                        if full_output:
                            self.on_log(f"JARVIS: {full_output}")
                    else:
                        pending_audio.clear()
                    input_parts.clear()
                    output_parts.clear()
                    pending_audio.clear()
                    self._current_turn_authorized = False

            tool_call = getattr(response, "tool_call", None)
            if tool_call:
                function_responses = []
                for call in getattr(tool_call, "function_calls", []) or []:
                    name = str(call.name)
                    args = dict(call.args or {})
                    if not self._current_turn_authorized and not self._is_awake():
                        result = {"ok": False, "message": "ignored_sleeping_no_wake_word", "silent": True}
                    else:
                        self._set_state("THINKING")
                        action_result = await asyncio.to_thread(self.platform.tool_call, name, args)
                        result = action_result.to_dict()
                        self.on_log(f"TOOL: {name} → {action_result.message}")
                    function_responses.append(types.FunctionResponse(id=call.id, name=name, response={"result": result}))
                await self.session.send_tool_response(function_responses=function_responses)

    async def _playback_loop(self) -> None:
        speaking = False
        while self.connected and not self._stop.is_set():
            try:
                chunk = await asyncio.wait_for(self.output_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if speaking and self.turn_done and self.turn_done.is_set() and self.output_queue.empty():
                    speaking = False
                    self.audio.set_speaking(False)
                    self.turn_done.clear()
                    self._refresh_followup()
                continue
            if not speaking:
                speaking = True
                self.audio.set_speaking(True)
                self._set_state("SPEAKING")
            await asyncio.to_thread(self.audio.play_pcm24, chunk)

    async def _standby_watchdog(self) -> None:
        was_awake = False
        while self.connected and not self._stop.is_set():
            await asyncio.sleep(0.25)
            remaining = max(0.0, self._awake_until - time.monotonic())
            self.on_countdown(remaining)
            if remaining > 0:
                was_awake = True
                continue
            if was_awake:
                was_awake = False
                if self._state not in {"SPEAKING", "THINKING"}:
                    self._force_sleep("tiempo agotado")

    async def _clear_output_queue(self) -> None:
        if self.output_queue is None:
            return
        while True:
            try:
                self.output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
