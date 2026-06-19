from __future__ import annotations
import asyncio
import collections
import math
import threading
import time
from typing import Callable
import numpy as np
import sounddevice as sd

class AdaptiveVad:
    def __init__(self, sensitivity: int = 78):
        self.sensitivity = max(1, min(100, sensitivity))
        self.noise_floor = 25.0
        self._samples: collections.deque[float] = collections.deque(maxlen=180)

    def calibrate(self, values: list[float]) -> None:
        clean = [x for x in values if math.isfinite(x)]
        if clean:
            self.noise_floor = max(1.0, float(np.percentile(clean, 35)))

    @property
    def threshold(self) -> float:
        # 100 = muy sensible. El umbral jamás queda por debajo del ruido real.
        ratio = 2.25 - (self.sensitivity / 100.0) * 1.15
        margin = 18.0 - (self.sensitivity / 100.0) * 12.0
        return max(6.0, self.noise_floor * ratio + margin)

    def update_silence(self, rms: float) -> None:
        if rms < self.threshold * 0.75:
            self._samples.append(rms)
            if len(self._samples) > 20:
                target = float(np.percentile(list(self._samples), 30))
                self.noise_floor = self.noise_floor * 0.985 + max(1.0, target) * 0.015

class LinearResampler:
    def __init__(self, source_rate: int, target_rate: int):
        self.source_rate = source_rate
        self.target_rate = target_rate
    def convert(self, pcm: bytes) -> bytes:
        if self.source_rate == self.target_rate or not pcm:
            return pcm
        src = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if len(src) < 2:
            return pcm
        count = max(1, round(len(src) * self.target_rate / self.source_rate))
        old = np.linspace(0.0, 1.0, len(src), endpoint=False)
        new = np.linspace(0.0, 1.0, count, endpoint=False)
        out = np.interp(new, old, src)
        return np.clip(out, -32768, 32767).astype(np.int16).tobytes()

class AudioService:
    def __init__(self, settings: dict, log: Callable[[str], None]):
        self.settings = settings
        self.log = log
        mic = settings["microphone"]
        self.sample_rate = int(mic.get("sample_rate", 16000))
        self.chunk_size = int(mic.get("chunk_size", 1024))
        self.vad = AdaptiveVad(int(mic.get("sensitivity", 78)))
        self.preroll_chunks = max(2, int((int(mic.get("preroll_ms", 550)) / 1000) * self.sample_rate / self.chunk_size))
        self.tail_seconds = int(mic.get("speech_tail_ms", 1100)) / 1000
        self.input_queue: asyncio.Queue[bytes] | None = None
        self.output_queue: asyncio.Queue[bytes] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.muted = False
        self.speaking = False
        self._last_voice = 0.0
        self._pre: collections.deque[bytes] = collections.deque(maxlen=self.preroll_chunks)

    @staticmethod
    def rms(data: bytes) -> float:
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(arr * arr))) if len(arr) else 0.0

    async def capture(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.input_queue = asyncio.Queue(maxsize=64)
        calibration: list[float] = []
        start = time.monotonic()
        calibration_seconds = float(self.settings["microphone"].get("calibration_seconds", 1.5))

        def enqueue(data: bytes) -> None:
            assert self.input_queue is not None
            if self.input_queue.full():
                try: self.input_queue.get_nowait()
                except asyncio.QueueEmpty: pass
            try: self.input_queue.put_nowait(data)
            except asyncio.QueueFull: pass

        def callback(indata, frames, time_info, status):
            if self.muted or self.speaking:
                return
            data = bytes(indata)
            level = self.rms(data)
            now = time.monotonic()
            if now - start < calibration_seconds:
                calibration.append(level)
                self._pre.append(data)
                return
            if calibration:
                self.vad.calibrate(calibration)
                calibration.clear()
                self.log(f"Micrófono calibrado: ruido={self.vad.noise_floor:.1f}, umbral={self.vad.threshold:.1f}")
            self._pre.append(data)
            if level >= self.vad.threshold:
                first = now - self._last_voice > self.tail_seconds
                self._last_voice = now
                if first:
                    for old in list(self._pre)[:-1]:
                        self.loop.call_soon_threadsafe(enqueue, old)
                self.loop.call_soon_threadsafe(enqueue, data)
            elif now - self._last_voice < self.tail_seconds:
                self.loop.call_soon_threadsafe(enqueue, data)
            else:
                self.vad.update_silence(level)

        device = self.settings["microphone"].get("device")
        with sd.RawInputStream(samplerate=self.sample_rate, blocksize=self.chunk_size, channels=1, dtype="int16", device=device, callback=callback):
            self.log("Entrada de audio abierta")
            while True:
                await asyncio.sleep(0.2)

    async def playback(self) -> None:
        self.output_queue = asyncio.Queue()
        output_cfg = self.settings["audio_output"]
        device = output_cfg.get("device")
        info = sd.query_devices(device, "output")
        target_rate = int(info["default_samplerate"] or 48000)
        source_rate = int(output_cfg.get("gemini_sample_rate", 24000))
        resampler = LinearResampler(source_rate, target_rate)
        stream = sd.RawOutputStream(samplerate=target_rate, channels=1, dtype="int16", device=device)
        stream.start()
        self.log(f"Audio de salida: {source_rate}Hz → {target_rate}Hz ({info['name']})")
        try:
            while True:
                data = await self.output_queue.get()
                self.speaking = True
                await asyncio.to_thread(stream.write, resampler.convert(data))
                if self.output_queue.empty():
                    self.speaking = False
        finally:
            self.speaking = False
            stream.stop(); stream.close()
