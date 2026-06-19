from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd


class AudioService:
    """Único propietario de la entrada y salida de audio.

    El callback de PortAudio nunca debe propagar excepciones: si una integración
    externa se desconecta, el micrófono continúa funcionando y el error se
    reporta mediante el bus de eventos.
    """

    def __init__(self, settings: dict, events):
        self.settings = settings
        self.events = events
        self.input_stream = None
        self.output_stream = None
        self.on_chunk: Callable[[bytes], None] | None = None
        self.on_level: Callable[[float, float], None] | None = None
        self._running = False
        self._muted = False
        self._speaking = False
        self._input_native_rate = 16000
        self._output_native_rate = 24000
        self._output_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._last_callback_error = 0.0

    @staticmethod
    def devices() -> list[dict]:
        result = []
        for index, device in enumerate(sd.query_devices()):
            result.append(
                {
                    "index": index,
                    "name": device["name"],
                    "inputs": int(device["max_input_channels"]),
                    "outputs": int(device["max_output_channels"]),
                    "rate": int(device["default_samplerate"]),
                }
            )
        return result

    @staticmethod
    def defaults():
        return sd.default.device

    def set_muted(self, value: bool) -> None:
        with self._state_lock:
            self._muted = bool(value)

    def set_speaking(self, value: bool) -> None:
        with self._state_lock:
            self._speaking = bool(value)

    @property
    def muted(self) -> bool:
        with self._state_lock:
            return self._muted

    def _resolve_input(self) -> tuple[int, int]:
        index = self.settings.get("input_device")
        if index is None:
            index = sd.default.device[0]
        info = sd.query_devices(int(index), "input")
        return int(index), int(info["default_samplerate"])

    def _resolve_output(self) -> tuple[int, int]:
        index = self.settings.get("output_device")
        if index is None:
            index = sd.default.device[1]
        info = sd.query_devices(int(index), "output")
        return int(index), int(info["default_samplerate"])

    @staticmethod
    def _resample_bytes(data: bytes, source_rate: int, target_rate: int) -> bytes:
        if source_rate == target_rate:
            return data
        samples = np.frombuffer(data, dtype=np.int16)
        if samples.size < 2:
            return data
        output_size = max(1, round(samples.size * target_rate / source_rate))
        positions = np.linspace(0, samples.size - 1, output_size)
        output = np.interp(positions, np.arange(samples.size), samples)
        return output.clip(-32768, 32767).astype(np.int16).tobytes()

    def _report_callback_error(self, exc: Exception) -> None:
        # Evita llenar el registro cientos de veces por segundo.
        now = time.monotonic()
        if now - self._last_callback_error >= 2.0:
            self._last_callback_error = now
            self.events.publish(
                "audio.callback.error",
                error_type=type(exc).__name__,
                message=str(exc),
            )

    def start(self, on_chunk, on_level) -> None:
        self.stop()
        self.on_chunk = on_chunk
        self.on_level = on_level

        index, native_rate = self._resolve_input()
        self._input_native_rate = native_rate
        blocksize = max(256, round(native_rate * 0.032))
        gain = float(self.settings.get("mic_gain", 1.0))

        with self._state_lock:
            self._running = True

        def callback(indata, frames, time_info, status):
            del frames, time_info
            try:
                with self._state_lock:
                    running = self._running
                    muted = self._muted
                    speaking = self._speaking

                if not running:
                    return

                if status:
                    self.events.publish("audio.warning", message=str(status))

                raw = indata.copy().reshape(-1)
                if gain != 1.0:
                    raw = np.clip(
                        raw.astype(np.float32) * gain,
                        -32768,
                        32767,
                    ).astype(np.int16)

                rms = (
                    float(np.sqrt(np.mean(raw.astype(np.float64) ** 2)))
                    if raw.size
                    else 0.0
                )
                level = min(
                    100.0,
                    max(0.0, 20 * np.log10(max(rms, 1) / 32768) + 90) * 1.7,
                )

                level_callback = self.on_level
                if level_callback is not None:
                    level_callback(level, rms)

                # Sin compuerta por defecto: JARVIS recibe la voz normal.
                chunk_callback = self.on_chunk
                if not muted and not speaking and chunk_callback is not None:
                    data = self._resample_bytes(raw.tobytes(), native_rate, 16000)
                    chunk_callback(data)
            except Exception as exc:
                # Nunca dejar que una excepción escape al callback CFFI/PortAudio.
                self._report_callback_error(exc)

        try:
            self.input_stream = sd.InputStream(
                device=index,
                samplerate=native_rate,
                channels=1,
                dtype="int16",
                blocksize=blocksize,
                callback=callback,
            )
            self.input_stream.start()
        except Exception:
            with self._state_lock:
                self._running = False
            self.input_stream = None
            raise

        self.events.publish(
            "audio.input.started",
            device=index,
            name=sd.query_devices(index)["name"],
            native_rate=native_rate,
        )

    def stop(self) -> None:
        with self._state_lock:
            self._running = False

        input_stream = self.input_stream
        self.input_stream = None
        if input_stream is not None:
            try:
                input_stream.stop()
            except Exception:
                pass
            try:
                input_stream.close()
            except Exception:
                pass

        output_stream = self.output_stream
        self.output_stream = None
        if output_stream is not None:
            try:
                output_stream.stop()
            except Exception:
                pass
            try:
                output_stream.close()
            except Exception:
                pass

    def restart(self, on_chunk=None, on_level=None) -> None:
        chunk_callback = on_chunk if on_chunk is not None else self.on_chunk
        level_callback = on_level if on_level is not None else self.on_level
        self.start(chunk_callback, level_callback)

    def play_pcm24(self, data: bytes) -> None:
        with self._output_lock:
            if self.output_stream is None:
                index, native_rate = self._resolve_output()
                self._output_native_rate = native_rate
                self.output_stream = sd.RawOutputStream(
                    device=index,
                    samplerate=native_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=0,
                )
                self.output_stream.start()
                self.events.publish(
                    "audio.output.started",
                    device=index,
                    name=sd.query_devices(index)["name"],
                    native_rate=native_rate,
                )

            converted = self._resample_bytes(
                data,
                24000,
                self._output_native_rate,
            )
            self.output_stream.write(converted)

    def record_test(self, seconds: float = 4.0):
        index, native_rate = self._resolve_input()
        frames = int(native_rate * seconds)
        recording = sd.rec(
            frames,
            samplerate=native_rate,
            channels=1,
            dtype="int16",
            device=index,
        )
        sd.wait()
        peak = int(np.max(np.abs(recording))) if recording.size else 0
        rms = (
            float(np.sqrt(np.mean(recording.astype(np.float64) ** 2)))
            if recording.size
            else 0.0
        )
        return recording, native_rate, peak, rms

    @staticmethod
    def play_test(recording, rate: int) -> None:
        sd.play(recording, samplerate=rate)
        sd.wait()
