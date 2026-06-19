from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from prp.core.config import ConfigManager
from prp.core.controller import PRPPlatform
from prp.services.audio import AudioService
from prp.services.gemini_live import GeminiLiveService
from prp.ui.main_window import JarvisUI


class PRPApplication:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.config = ConfigManager(self.base_dir)
        face = self.base_dir / "face.png"
        self.ui = JarvisUI(str(face) if face.exists() else "")
        self.platform = PRPPlatform(self.base_dir, self.config, ui=self.ui)
        audio_settings = (self.config.app().get("audio") or {})
        self.audio = AudioService(audio_settings, self.platform.event_bus)
        self.live = GeminiLiveService(
            self.config,
            self.platform,
            self.audio,
            self.platform.event_bus,
            on_state=self.ui.set_state,
            on_log=self.ui.write_log,
            on_countdown=self.ui.set_standby_countdown,
        )
        self.platform.attach_audio(self.audio, self.restart_audio)
        self.ui.attach_platform(self.platform)
        self.ui.on_text_command = self.live.send_text_threadsafe
        self.ui.on_interrupt_command = self.live.interrupt_threadsafe
        self.ui.on_esp32_refresh_ports = self.refresh_ports
        self.ui.on_esp32_connect = self.connect_primary_node
        self.ui.on_mute_changed = self.audio.set_muted
        self.ui.on_close = self.shutdown
        self._thread: threading.Thread | None = None
        self._closed = threading.Event()
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        self.platform.event_bus.subscribe("esp32.node.online", self._on_esp32_online)
        self.platform.event_bus.subscribe("esp32.node.offline", self._on_esp32_offline)
        self.platform.event_bus.subscribe("audio.callback.error", lambda e: self.ui.write_log(f"ERR AUDIO: {e.payload.get('message', '')}"))
        self.platform.event_bus.subscribe("audio.input.started", lambda e: self.ui.write_log(
            f"SYS: Micrófono abierto: {e.payload.get('name')} · {e.payload.get('native_rate')}Hz"
        ))
        self.platform.event_bus.subscribe("audio.output.started", lambda e: self.ui.write_log(
            f"SYS: Audio de salida: 24000Hz → {e.payload.get('native_rate')}Hz · {e.payload.get('name')}"
        ))

    def _on_esp32_online(self, event) -> None:
        node = event.payload.get("node", {})
        self.ui.set_esp32_status("ONLINE", str(node.get("port", "")), f"Firmware {event.payload.get('hello', {}).get('firmware', '--')} · GPIO sincronizados")

    def _on_esp32_offline(self, event) -> None:
        node_id = str(event.payload.get("node_id", "esp32_principal"))
        node = next((n for n in self.platform.esp32.list_nodes() if n.get("id") == node_id), {})
        self.ui.set_esp32_status("DISCONNECTED", str(node.get("port", "")), str(event.payload.get("error", "sin conexión")))

    def start(self) -> None:
        self.refresh_ports()
        primary = next((n for n in self.platform.esp32.list_nodes() if n.get("id") == "esp32_principal"), {})
        self.ui.set_esp32_status("UNKNOWN", str(primary.get("port", "COM6")), "pulsa CONECTAR o usa el Centro de Control")
        try:
            self.audio.start(self.live.enqueue_audio_threadsafe, self._on_audio_level)
        except Exception as exc:
            self.ui.write_log(f"ERR: No pude abrir el micrófono: {exc}")
            self.ui.set_state("OFFLINE")
        self._thread = threading.Thread(target=self._run_async, daemon=True, name="PRPGeminiRuntime")
        self._thread.start()
        threading.Thread(target=self._auto_connect_primary, daemon=True, name="PRPESP32AutoConnect").start()


    def _auto_connect_primary(self) -> None:
        """Try the saved node once at startup without blocking the interface."""
        time.sleep(1.0)
        if self._closed.is_set():
            return
        node = next((n for n in self.platform.esp32.list_nodes() if n.get("id") == "esp32_principal"), {})
        if not node or not node.get("enabled", True) or not str(node.get("port", "")).strip():
            return
        port = str(node.get("port", ""))
        self.ui.set_esp32_status("CONNECTING", port, "conexión automática y sincronización GPIO")
        result = self.platform.esp32.connect("esp32_principal", auto_sync=True)
        if result.ok:
            self.ui.set_esp32_status("ONLINE", port, "Nodo listo · configuración GPIO sincronizada")
            self.ui.write_log(f"ESP32: {result.message}")
        else:
            self.ui.set_esp32_status("DISCONNECTED", port, result.message)
            self.ui.write_log(f"SYS ESP32: {result.message}")

    def _run_async(self) -> None:
        try:
            asyncio.run(self.live.run_forever())
        except Exception as exc:
            self.ui.write_log(f"ERR: Runtime asíncrono: {type(exc).__name__}: {exc}")

    def _on_audio_level(self, level: float, rms: float, peak: float) -> None:
        del peak
        self.ui.set_audio_level(level, rms)

    def restart_audio(self) -> None:
        try:
            settings = self.platform.get_audio_settings()
            self.audio.update_settings(settings)
            self.audio.restart(self.live.enqueue_audio_threadsafe, self._on_audio_level)
            self.audio.set_muted(self.ui.muted)
            self.ui.write_log("SYS: Audio reiniciado con la nueva configuración.")
        except Exception as exc:
            self.ui.write_log(f"ERR: No pude reiniciar el audio: {exc}")
            raise

    def refresh_ports(self):
        ports = self.platform.esp32.list_ports()
        primary = next((n for n in self.platform.esp32.list_nodes() if n.get("id") == "esp32_principal"), {})
        self.ui.update_esp32_ports(ports, str(primary.get("port", "COM6")))
        return ports

    def connect_primary_node(self, port: str):
        self.ui.set_esp32_status("CONNECTING", port, "saludando y sincronizando GPIO")
        try:
            self.platform.esp32.set_primary_port(port)
            result = self.platform.esp32.connect("esp32_principal", auto_sync=True)
            if result.ok:
                self.ui.set_esp32_status("ONLINE", port, result.message + " Configuración sincronizada.")
                self.ui.write_log(f"ESP32: {result.message}")
            else:
                self.ui.set_esp32_status("DISCONNECTED", port, result.message)
                self.ui.write_log(f"ERR ESP32: {result.message}")
            return result
        except Exception as exc:
            self.ui.set_esp32_status("DISCONNECTED", port, str(exc))
            self.ui.write_log(f"ERR ESP32: {exc}")
            return None

    def shutdown(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.live.stop()
        except Exception:
            pass
        try:
            self.audio.stop()
        except Exception:
            pass
        try:
            self.platform.shutdown()
        except Exception:
            pass
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)

    def run(self) -> int:
        self.start()
        self.ui.root.mainloop()
        self.shutdown()
        return 0
