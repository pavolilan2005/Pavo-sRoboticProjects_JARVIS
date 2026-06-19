from __future__ import annotations

import collections
import math
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd


class AudioService:
    """Single owner of microphone and speakers.

    The input stream always exposes a live level meter. By default audio is sent
    continuously to Gemini, which avoids the old "shout to wake" problem. An
    optional adaptive gate can be enabled to reduce keyboard/fan noise; it keeps
    a pre-roll buffer so the beginning of "Jarvis" is not lost.
    """

    INPUT_RATE = 16000
    MODEL_OUTPUT_RATE = 24000

    def __init__(self, settings: dict, events):
        self.settings = dict(settings or {})
        self.events = events
        self.input_stream = None
        self.output_stream = None
        self.on_chunk: Callable[[bytes], None] | None = None
        self.on_level: Callable[[float, float, float], None] | None = None
        self._running = False
        self._muted = False
        self._speaking = False
        self._state_lock = threading.RLock()
        self._output_lock = threading.RLock()
        self._last_callback_error = 0.0
        self._input_native_rate = self.INPUT_RATE
        self._output_native_rate = self.MODEL_OUTPUT_RATE
        self._noise_floor = 12.0
        self._speech_until = 0.0
        self._pre_roll = collections.deque(maxlen=32)

    @staticmethod
    def devices() -> list[dict]:
        result = []
        for index, device in enumerate(sd.query_devices()):
            result.append(
                {
                    "index": index,
                    "name": str(device["name"]),
                    "inputs": int(device["max_input_channels"]),
                    "outputs": int(device["max_output_channels"]),
                    "rate": int(device["default_samplerate"]),
                }
            )
        return result

    @staticmethod
    def defaults():
        return sd.default.device

    def status(self) -> dict:
        with self._state_lock:
            return {
                "running": self._running,
                "muted": self._muted,
                "speaking": self._speaking,
                "input_device": self.settings.get("input_device"),
                "output_device": self.settings.get("output_device"),
                "mic_gain": float(self.settings.get("mic_gain", 1.35)),
                "noise_gate_enabled": bool(self.settings.get("noise_gate_enabled", False)),
                "sensitivity": int(self.settings.get("sensitivity", 82)),
                "noise_floor": self._noise_floor,
                "input_native_rate": self._input_native_rate,
                "output_native_rate": self._output_native_rate,
            }

    def update_settings(self, settings: dict) -> None:
        with self._state_lock:
            self.settings = dict(settings or {})

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
        if index in (None, "", -1, "-1"):
            index = sd.default.device[0]
        info = sd.query_devices(int(index), "input")
        return int(index), int(info["default_samplerate"])

    def _resolve_output(self) -> tuple[int, int]:
        index = self.settings.get("output_device")
        if index in (None, "", -1, "-1"):
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
        now = time.monotonic()
        if now - self._last_callback_error >= 2.0:
            self._last_callback_error = now
            self.events.publish("audio.callback.error", {"error_type": type(exc).__name__, "message": str(exc)}, "audio")

    def start(self, on_chunk, on_level) -> None:
        self.stop()
        self.on_chunk = on_chunk
        self.on_level = on_level
        index, native_rate = self._resolve_input()
        self._input_native_rate = native_rate
        blocksize = max(256, round(native_rate * 0.032))
        with self._state_lock:
            self._running = True

        def callback(indata, frames, time_info, status):
            del frames, time_info
            try:
                with self._state_lock:
                    running = self._running
                    muted = self._muted
                    speaking = self._speaking
                    settings = dict(self.settings)
                if not running:
                    return
                if status:
                    self.events.publish("audio.warning", {"message": str(status)}, "audio")

                raw = indata.copy().reshape(-1)
                gain = max(0.1, min(4.0, float(settings.get("mic_gain", 1.35))))
                if gain != 1.0:
                    raw = np.clip(raw.astype(np.float32) * gain, -32768, 32767).astype(np.int16)

                rms = float(np.sqrt(np.mean(raw.astype(np.float64) ** 2))) if raw.size else 0.0
                peak = float(np.max(np.abs(raw))) if raw.size else 0.0
                db = 20.0 * math.log10(max(rms, 1.0) / 32768.0)
                level = max(0.0, min(100.0, (db + 72.0) * 2.3))

                level_callback = self.on_level
                if level_callback is not None:
                    level_callback(level, rms, peak)

                if muted or speaking:
                    return

                data = self._resample_bytes(raw.tobytes(), native_rate, self.INPUT_RATE)
                chunk_callback = self.on_chunk
                if chunk_callback is None:
                    return

                if not bool(settings.get("noise_gate_enabled", False)):
                    chunk_callback(data)
                    return

                # Adaptive gate. High sensitivity means a lower multiplier.
                sensitivity = max(1, min(100, int(settings.get("sensitivity", 82))))
                multiplier = 4.2 - (sensitivity / 100.0) * 2.95  # 1.25 .. 4.17
                threshold = max(14.0, self._noise_floor * multiplier)
                now = time.monotonic()
                self._pre_roll.append(data)

                if rms < threshold * 0.72 and now > self._speech_until:
                    self._noise_floor = max(2.0, min(5000.0, self._noise_floor * 0.985 + rms * 0.015))

                if rms >= threshold:
                    self._speech_until = now + max(0.45, float(settings.get("speech_trail_ms", 1100)) / 1000.0)
                    while self._pre_roll:
                        chunk_callback(self._pre_roll.popleft())
                elif now < self._speech_until:
                    chunk_callback(data)
            except Exception as exc:
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
            {"device": index, "name": sd.query_devices(index)["name"], "native_rate": native_rate},
            "audio",
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
        self.start(on_chunk if on_chunk is not None else self.on_chunk, on_level if on_level is not None else self.on_level)

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
                    {"device": index, "name": sd.query_devices(index)["name"], "native_rate": native_rate},
                    "audio",
                )
            converted = self._resample_bytes(data, self.MODEL_OUTPUT_RATE, self._output_native_rate)
            self.output_stream.write(converted)

    def record_test(self, seconds: float = 4.0):
        was_running = self.status()["running"]
        if was_running:
            self.stop()
        try:
            index, native_rate = self._resolve_input()
            frames = int(native_rate * seconds)
            recording = sd.rec(frames, samplerate=native_rate, channels=1, dtype="int16", device=index)
            sd.wait()
            peak = int(np.max(np.abs(recording))) if recording.size else 0
            rms = float(np.sqrt(np.mean(recording.astype(np.float64) ** 2))) if recording.size else 0.0
            return recording, native_rate, peak, rms
        finally:
            if was_running:
                self.start(self.on_chunk, self.on_level)

    @staticmethod
    def play_test(recording, rate: int) -> None:
        sd.play(recording, samplerate=rate)
        sd.wait()
