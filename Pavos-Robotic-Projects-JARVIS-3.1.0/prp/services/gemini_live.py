from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from google import genai
from google.genai import types


class GeminiLiveService:
    """Conexión única y persistente con Gemini Live.

    El servicio mantiene vivo su event loop aun cuando todavía no existe una API
    key. De esta forma el micrófono y la interfaz pueden seguir funcionando sin
    que PortAudio intente escribir sobre un loop cerrado.
    """

    def __init__(self, controller, callbacks):
        self.controller = controller
        self.cb = callbacks
        self.session = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.mic_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=80)
        self.play_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.running = False
        self.awake_until = 0.0
        self.authorized = False
        self.pending_audio: list[bytes] = []
        self._run_task: asyncio.Task | None = None
        self._credentials_changed: asyncio.Event | None = None
        self._missing_key_reported = False
        app = controller.config.load("app.json", {}) or {}
        self.settings = app

    def push_mic(self, data: bytes) -> None:
        """Recibe audio desde PortAudio sin asumir que el loop sigue abierto."""
        loop = self.loop
        if (
            not self.running
            or self.session is None
            or loop is None
            or loop.is_closed()
        ):
            return

        def put() -> None:
            if not self.running or self.session is None:
                return
            if self.mic_queue.full():
                try:
                    self.mic_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                self.mic_queue.put_nowait(data)
            except asyncio.QueueFull:
                pass

        try:
            loop.call_soon_threadsafe(put)
        except RuntimeError:
            # El proceso se está cerrando o el loop ya terminó. No es un error
            # de PortAudio y no debe escapar al callback CFFI.
            return

    def credentials_updated(self) -> None:
        """Despierta el servicio cuando la UI guarda una API key."""
        loop = self.loop
        event = self._credentials_changed
        if loop is None or event is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            pass

    def request_stop(self) -> None:
        """Detiene el servicio desde el hilo de Qt."""
        self.running = False
        loop = self.loop
        task = self._run_task
        if loop is None or loop.is_closed():
            return

        def cancel() -> None:
            if task is not None and not task.done():
                task.cancel()

        try:
            loop.call_soon_threadsafe(cancel)
        except RuntimeError:
            pass

    def _wake(self) -> None:
        seconds = float(
            self.settings.get("assistant", {}).get("followup_seconds", 30)
        )
        self.awake_until = time.monotonic() + seconds
        self.authorized = True
        self.cb.state("LISTENING")

    def _is_awake(self) -> bool:
        return time.monotonic() < self.awake_until

    def _has_wake(self, text: str) -> bool:
        normalized = re.sub(r"[^a-záéíóúñ ]", " ", text.lower())
        wake_words = self.settings.get("assistant", {}).get(
            "wake_words",
            ["jarvis"],
        )
        return any(word in normalized for word in wake_words)

    def config(self) -> types.LiveConnectConfig:
        tools = [
            {
                "function_declarations": [
                    {
                        "name": "open_app",
                        "description": "Abre una aplicación",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {"name": {"type": "STRING"}},
                            "required": ["name"],
                        },
                    },
                    {
                        "name": "play_music",
                        "description": "Reproduce canción, artista, álbum o playlist",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "query": {"type": "STRING"},
                                "target_type": {"type": "STRING"},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "play_media_alias",
                        "description": "Reproduce un alias multimedia personal",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {"alias": {"type": "STRING"}},
                            "required": ["alias"],
                        },
                    },
                    {
                        "name": "media_control",
                        "description": "Controla Spotify",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {"action": {"type": "STRING"}},
                            "required": ["action"],
                        },
                    },
                    {
                        "name": "run_routine",
                        "description": "Ejecuta una rutina",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {"routine_id": {"type": "STRING"}},
                            "required": ["routine_id"],
                        },
                    },
                    {
                        "name": "set_home_device",
                        "description": "Controla un dispositivo domótico",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "device": {"type": "STRING"},
                                "state": {"type": "STRING"},
                            },
                            "required": ["device", "state"],
                        },
                    },
                    {
                        "name": "obs_scene",
                        "description": "Cambia la escena de OBS",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {"scene": {"type": "STRING"}},
                            "required": ["scene"],
                        },
                    },
                ]
            }
        ]
        prompt = (
            "Eres JARVIS, asistente de Pavo's Robotic Projects. "
            "Responde en español, breve y natural. Para audio del micrófono, "
            "solo responde o llama herramientas cuando la frase incluya Jarvis "
            "o sea un seguimiento inmediato de una conversación activa. "
            "No afirmes que ejecutaste algo sin usar una herramienta. "
            "Interpreta claramente canción vs artista vs playlist."
        )
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription={},
            output_audio_transcription={},
            system_instruction=prompt,
            tools=tools,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.settings.get("gemini", {}).get(
                            "voice",
                            "Charon",
                        )
                    )
                )
            ),
        )

    async def send_text(self, text: str) -> bool:
        session = self.session
        if session is None:
            self.cb.log(
                "JARVIS está OFFLINE. Configura Gemini API key en INTEGRACIONES."
            )
            return False
        self._wake()
        await session.send_realtime_input(text=text)
        return True

    async def _send_mic(self) -> None:
        while self.running and self.session is not None:
            data = await self.mic_queue.get()
            session = self.session
            if session is None:
                continue
            await session.send_realtime_input(
                audio=types.Blob(
                    data=data,
                    mime_type="audio/pcm;rate=16000",
                )
            )

    async def _execute_tool(self, function_call):
        args = dict(function_call.args or {})
        mapping: dict[str, tuple[str, dict[str, Any]]] = {
            "open_app": (
                "pc.open_app",
                {"name": args.get("name", "")},
            ),
            "play_music": (
                "spotify.play",
                {
                    "query": args.get("query", ""),
                    "target_type": args.get("target_type", "track"),
                },
            ),
            "play_media_alias": (
                "spotify.play_alias",
                {"alias": args.get("alias", "")},
            ),
            "run_routine": (
                "routine.run",
                {"routine_id": args.get("routine_id", "")},
            ),
            "set_home_device": (
                "home.set",
                {
                    "device": args.get("device", ""),
                    "state": args.get("state", "on"),
                },
            ),
            "obs_scene": (
                "obs.set_scene",
                {"scene": args.get("scene", "")},
            ),
        }

        if function_call.name == "media_control":
            capability = {
                "pause": "spotify.pause",
                "resume": "spotify.resume",
                "play": "spotify.resume",
                "next": "spotify.next",
            }.get(str(args.get("action", "")).lower(), "spotify.resume")
            parameters = {}
        else:
            capability, parameters = mapping.get(function_call.name, ("", {}))

        result = await self.controller.execute(capability, parameters)
        return types.FunctionResponse(
            id=function_call.id,
            name=function_call.name,
            response={"result": result.message, "ok": result.ok},
        )

    async def _receive(self) -> None:
        input_buffer: list[str] = []
        output_buffer: list[str] = []

        while self.running and self.session is not None:
            session = self.session
            async for response in session.receive():
                if response.server_content:
                    content = response.server_content

                    if (
                        content.input_transcription
                        and content.input_transcription.text
                    ):
                        text = content.input_transcription.text.strip()
                        input_buffer.append(text)
                        if self._has_wake(text) or self._is_awake():
                            self._wake()
                            self._flush_pending()

                    if (
                        content.output_transcription
                        and content.output_transcription.text
                    ):
                        output_buffer.append(
                            content.output_transcription.text.strip()
                        )

                    if content.model_turn:
                        for part in content.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                if self.authorized or self._is_awake():
                                    self.play_queue.put_nowait(
                                        part.inline_data.data
                                    )
                                else:
                                    self.pending_audio.append(
                                        part.inline_data.data
                                    )
                                    self.pending_audio = self.pending_audio[-180:]

                    if content.turn_complete:
                        full_input = " ".join(input_buffer).strip()
                        full_output = " ".join(output_buffer).strip()
                        allowed = (
                            self.authorized
                            or self._has_wake(full_input)
                            or self._is_awake()
                        )
                        if allowed:
                            if full_input:
                                self.cb.transcript("TÚ", full_input)
                            if full_output:
                                self.cb.transcript("JARVIS", full_output)
                        else:
                            self.pending_audio.clear()

                        input_buffer.clear()
                        output_buffer.clear()
                        self.authorized = False

                if response.tool_call:
                    replies = []
                    for function_call in response.tool_call.function_calls:
                        if self.authorized or self._is_awake():
                            replies.append(
                                await self._execute_tool(function_call)
                            )
                        else:
                            replies.append(
                                types.FunctionResponse(
                                    id=function_call.id,
                                    name=function_call.name,
                                    response={
                                        "result": "ignored_sleeping",
                                        "ok": False,
                                    },
                                )
                            )
                    await session.send_tool_response(
                        function_responses=replies
                    )

    def _flush_pending(self) -> None:
        for block in self.pending_audio:
            self.play_queue.put_nowait(block)
        self.pending_audio.clear()

    async def _play(self) -> None:
        try:
            while self.running and self.session is not None:
                data = await self.play_queue.get()
                self.controller.audio.set_speaking(True)
                self.cb.state("SPEAKING")
                await asyncio.to_thread(
                    self.controller.audio.play_pcm24,
                    data,
                )
                if self.play_queue.empty():
                    self.controller.audio.set_speaking(False)
                    self.awake_until = time.monotonic() + float(
                        self.settings.get("assistant", {}).get(
                            "followup_seconds",
                            30,
                        )
                    )
                    self.cb.state("LISTENING")
        finally:
            self.controller.audio.set_speaking(False)

    @staticmethod
    def _flatten_exception_group(group: BaseException) -> list[BaseException]:
        children = getattr(group, "exceptions", None)
        if not children:
            return [group]
        flattened: list[BaseException] = []
        for child in children:
            flattened.extend(
                GeminiLiveService._flatten_exception_group(child)
            )
        return flattened

    async def _wait_for_credentials(self) -> str:
        while self.running:
            key = str(
                self.controller.config.secrets().get("gemini_api_key", "")
            ).strip()
            if key:
                self._missing_key_reported = False
                return key

            self.cb.state("OFFLINE")
            if not self._missing_key_reported:
                self._missing_key_reported = True
                self.cb.log(
                    "Gemini API key no configurada. Abre INTEGRACIONES, "
                    "guarda la clave y JARVIS intentará conectarse automáticamente."
                )

            event = self._credentials_changed
            if event is None:
                await asyncio.sleep(1.0)
                continue
            try:
                await asyncio.wait_for(event.wait(), timeout=1.0)
                event.clear()
            except asyncio.TimeoutError:
                pass

        return ""

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._run_task = asyncio.current_task()
        self._credentials_changed = asyncio.Event()
        self.running = True
        reconnect_delay = 1

        try:
            while self.running:
                api_key = await self._wait_for_credentials()
                if not api_key or not self.running:
                    break

                client = genai.Client(api_key=api_key)
                try:
                    self.cb.state("CONNECTING")
                    model = self.settings.get("gemini", {}).get(
                        "model",
                        "gemini-3.1-flash-live-preview",
                    )
                    async with client.aio.live.connect(
                        model=model,
                        config=self.config(),
                    ) as session:
                        self.session = session
                        reconnect_delay = 1
                        self.cb.log(
                            "JARVIS online. Di Jarvis con voz normal."
                        )
                        self.cb.state("SLEEPING")
                        async with asyncio.TaskGroup() as task_group:
                            task_group.create_task(
                                self._send_mic(),
                                name="send-microphone",
                            )
                            task_group.create_task(
                                self._receive(),
                                name="receive-gemini",
                            )
                            task_group.create_task(
                                self._play(),
                                name="play-response",
                            )
                except asyncio.CancelledError:
                    raise
                except BaseExceptionGroup as group:
                    for error in self._flatten_exception_group(group):
                        if isinstance(error, asyncio.CancelledError):
                            continue
                        self.cb.log(
                            "Error de sesión: "
                            f"{type(error).__name__}: {error}"
                        )
                except Exception as error:
                    self.cb.log(
                        "Error de sesión: "
                        f"{type(error).__name__}: {error}"
                    )
                finally:
                    self.session = None
                    self.authorized = False
                    self.pending_audio.clear()
                    self.controller.audio.set_speaking(False)
                    while not self.mic_queue.empty():
                        try:
                            self.mic_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                if self.running:
                    self.cb.state("RECONNECTING")
                    self.cb.log(
                        f"Reconectando Gemini en {reconnect_delay}s..."
                    )
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(20, reconnect_delay * 2)
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            self.session = None
            self.controller.audio.set_speaking(False)
            self.cb.state("OFFLINE")
            self._run_task = None
            self._credentials_changed = None
            self.loop = None
