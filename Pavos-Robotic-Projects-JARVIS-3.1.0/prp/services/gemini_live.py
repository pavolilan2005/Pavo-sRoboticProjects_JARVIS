from __future__ import annotations
import asyncio
import re
import time
import unicodedata
from typing import Any, Callable
from google import genai
from google.genai import types
from prp.core.controller import PrpController
from prp.services.audio_service import AudioService

class GeminiLiveService:
    def __init__(self, controller: PrpController, audio: AudioService, state: Callable[[str], None], transcript: Callable[[str, str], None], log: Callable[[str], None]):
        self.controller = controller
        self.audio = audio
        self.state = state
        self.transcript = transcript
        self.log = log
        self.session = None
        self._awake_until = 0.0
        self._authorized = False
        app = controller.config.load("app.json", {}) or {}
        self.app = app
        self.wake_words = tuple(app.get("wake_words", ["jarvis"]))
        self.awake_window = float(app.get("awake_window_seconds", 30))
        self.followup_window = float(app.get("followup_window_seconds", 20))

    @staticmethod
    def _norm(text: str) -> str:
        value = unicodedata.normalize("NFKD", text.lower())
        value = "".join(c for c in value if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9 ]+", " ", value)

    def _has_wake(self, text: str) -> bool:
        norm = self._norm(text)
        return any(re.search(rf"\b{re.escape(self._norm(w))}\b", norm) for w in self.wake_words)

    def wake(self, reason: str = "manual") -> None:
        self._awake_until = time.monotonic() + self.awake_window
        self._authorized = True
        self.state("LISTENING")
        self.log(f"Activo durante {int(self.awake_window)}s ({reason})")

    def sleeping(self) -> bool:
        return time.monotonic() >= self._awake_until

    def tool_declarations(self) -> list[dict[str, Any]]:
        return [
            {"name":"run_routine","description":"Ejecuta una rutina configurada","parameters":{"type":"OBJECT","properties":{"routine":{"type":"STRING"}},"required":["routine"]}},
            {"name":"control_mode","description":"Activa o desactiva un modo","parameters":{"type":"OBJECT","properties":{"mode":{"type":"STRING"},"action":{"type":"STRING","enum":["start","stop"]}},"required":["mode","action"]}},
            {"name":"spotify","description":"Controla Spotify y reproduce canciones, artistas, álbumes, playlists o alias","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","enum":["play","play_alias","pause","volume","status"]},"query":{"type":"STRING"},"kind":{"type":"STRING"},"volume":{"type":"INTEGER"}},"required":["action"]}},
            {"name":"obs","description":"Controla OBS","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","enum":["status","scene","record_start","record_stop"]},"scene":{"type":"STRING"}},"required":["action"]}},
            {"name":"device","description":"Controla un dispositivo domótico configurado","parameters":{"type":"OBJECT","properties":{"device_id":{"type":"STRING"},"action":{"type":"STRING"},"value":{}},"required":["device_id","action"]}},
            {"name":"pc_status","description":"Consulta CPU RAM disco y batería","parameters":{"type":"OBJECT","properties":{}}},
            {"name":"open_app","description":"Abre una aplicación","parameters":{"type":"OBJECT","properties":{"name":{"type":"STRING"}},"required":["name"]}}
        ]

    def config(self) -> types.LiveConnectConfig:
        prompt = """Eres JARVIS, asistente de Pavo's Robotic Projects. Habla español natural, breve y directo. Usa herramientas para acciones reales; jamás afirmes que hiciste algo sin resultado exitoso. Cuando el usuario pida música distingue canción, artista, álbum, playlist y alias. Si dice 'mi playlist' prioriza alias personales. Mientras el sistema está dormido solo atiende audio que incluya Jarvis; durante la ventana activa acepta seguimientos. Para iniciar grabación o sincronizar hardware confirma antes."""
        return types.LiveConnectConfig(response_modalities=["AUDIO"], input_audio_transcription={}, output_audio_transcription={}, system_instruction=prompt, tools=[{"function_declarations": self.tool_declarations()}], speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon"))))

    async def send_text(self, text: str) -> None:
        if not self.session: return
        self.wake("texto")
        await self.session.send_client_content(turns={"parts":[{"text":text}]}, turn_complete=True)

    async def run(self) -> None:
        secrets = self.controller.config.secrets()
        key = secrets.get("gemini_api_key", "")
        if not key: raise RuntimeError("Falta gemini_api_key en config/secrets.json")
        client = genai.Client(api_key=key, http_options={"api_version":"v1beta"})
        model = self.app.get("gemini_model")
        while True:
            try:
                self.state("CONNECTING")
                async with client.aio.live.connect(model=model, config=self.config()) as session:
                    self.session = session
                    self.state("SLEEPING")
                    self.log("JARVIS online. Di Jarvis con voz normal.")
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self.audio.capture())
                        tg.create_task(self.audio.playback())
                        tg.create_task(self._send_audio())
                        tg.create_task(self._receive())
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.log(f"Sesión Live: {type(exc).__name__}: {exc}. Reconectando...")
                self.session = None
                await asyncio.sleep(2)

    async def _send_audio(self) -> None:
        while self.audio.input_queue is None: await asyncio.sleep(0.05)
        while True:
            data = await self.audio.input_queue.get()
            await self.session.send_realtime_input(audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={self.audio.sample_rate}"))

    async def _receive(self) -> None:
        in_parts: list[str] = []; out_parts: list[str] = []
        async for response in self.session.receive():
            server = response.server_content
            if server:
                if server.input_transcription and server.input_transcription.text:
                    text = server.input_transcription.text.strip(); in_parts.append(text)
                    if self._has_wake(text): self.wake("wake word")
                    elif not self.sleeping(): self._authorized = True
                if server.output_transcription and server.output_transcription.text:
                    out_parts.append(server.output_transcription.text.strip())
                turn = getattr(server, "model_turn", None)
                if turn:
                    for part in turn.parts or []:
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data and (self._authorized or not self.sleeping()):
                            while self.audio.output_queue is None: await asyncio.sleep(0.01)
                            await self.audio.output_queue.put(inline.data)
                if server.turn_complete:
                    user_text = " ".join(in_parts).strip(); assistant_text = " ".join(out_parts).strip()
                    if self._authorized or self._has_wake(user_text):
                        if user_text: self.transcript("Tú", user_text)
                        if assistant_text: self.transcript("Jarvis", assistant_text)
                        self._awake_until = time.monotonic() + self.followup_window
                    in_parts.clear(); out_parts.clear(); self._authorized = False
                    self.state("LISTENING" if not self.sleeping() else "SLEEPING")
            if response.tool_call:
                replies = []
                for call in response.tool_call.function_calls:
                    result = await self._execute_tool(call.name, dict(call.args or {})) if (self._authorized or not self.sleeping()) else None
                    replies.append(types.FunctionResponse(id=call.id, name=call.name, response={"result": result.message if result else "ignored_sleeping", "ok": bool(result and result.ok)}))
                await self.session.send_tool_response(function_responses=replies)

    async def _execute_tool(self, name: str, args: dict[str, Any]):
        mapping = {
            "run_routine": ("routine.run", {"routine_id_or_alias": args.get("routine", "")}),
            "control_mode": (f"mode.{args.get('action','start')}", {"mode_id": args.get("mode", "")}),
            "pc_status": ("pc.status", {}),
            "open_app": ("app.open", {"name": args.get("name", "")}),
            "device": ("device.control", args),
        }
        if name == "spotify":
            action = args.get("action")
            if action == "play": mapping[name] = ("spotify.play", {"query":args.get("query", ""), "kind":args.get("kind", "track")})
            elif action == "play_alias": mapping[name] = ("spotify.play_alias", {"alias":args.get("query", "")})
            elif action == "volume": mapping[name] = ("spotify.volume", {"volume":args.get("volume", 30)})
            else: mapping[name] = (f"spotify.{action}", {})
        elif name == "obs":
            action = args.get("action")
            if action == "scene": mapping[name] = ("obs.scene", {"scene":args.get("scene", "")})
            elif action == "record_start": mapping[name] = ("obs.record.start", {})
            elif action == "record_stop": mapping[name] = ("obs.record.stop", {})
            else: mapping[name] = ("obs.status", {})
        cap, cap_args = mapping.get(name, (name, args))
        return await self.controller.execute(cap, cap_args)
