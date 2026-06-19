from __future__ import annotations
import threading,time
from collections import deque
import numpy as np
import sounddevice as sd

class AudioService:
    """Único propietario de entrada/salida de audio."""
    def __init__(self,settings:dict,events):
        self.settings=settings; self.events=events
        self.input_stream=None; self.output_stream=None
        self.on_chunk=None; self.on_level=None
        self._running=False; self._muted=False; self._speaking=False
        self._input_native_rate=16000; self._output_native_rate=24000
        self._output_lock=threading.Lock()
    @staticmethod
    def devices():
        result=[]
        for i,d in enumerate(sd.query_devices()):
            result.append({'index':i,'name':d['name'],'inputs':int(d['max_input_channels']),'outputs':int(d['max_output_channels']),'rate':int(d['default_samplerate'])})
        return result
    @staticmethod
    def defaults(): return sd.default.device
    def set_muted(self,value:bool): self._muted=value
    def set_speaking(self,value:bool): self._speaking=value
    @property
    def muted(self): return self._muted
    def _resolve_input(self):
        idx=self.settings.get('input_device')
        if idx is None: idx=sd.default.device[0]
        info=sd.query_devices(int(idx),'input'); return int(idx),int(info['default_samplerate'])
    def _resolve_output(self):
        idx=self.settings.get('output_device')
        if idx is None: idx=sd.default.device[1]
        info=sd.query_devices(int(idx),'output'); return int(idx),int(info['default_samplerate'])
    @staticmethod
    def _resample_bytes(data:bytes,src:int,dst:int)->bytes:
        if src==dst:return data
        x=np.frombuffer(data,dtype=np.int16)
        if x.size<2:return data
        n=max(1,round(x.size*dst/src)); pos=np.linspace(0,x.size-1,n)
        y=np.interp(pos,np.arange(x.size),x).clip(-32768,32767).astype(np.int16)
        return y.tobytes()
    def start(self,on_chunk,on_level):
        self.stop(); self.on_chunk=on_chunk; self.on_level=on_level
        idx,native=self._resolve_input(); self._input_native_rate=native
        block=max(256,round(native*0.032))
        gain=float(self.settings.get('mic_gain',1.0))
        def callback(indata,frames,t,status):
            if status:self.events.publish('audio.warning',message=str(status))
            raw=indata.copy().reshape(-1)
            if gain!=1.0: raw=np.clip(raw.astype(np.float32)*gain,-32768,32767).astype(np.int16)
            rms=float(np.sqrt(np.mean(raw.astype(np.float64)**2))) if raw.size else 0.0
            level=min(100.0,max(0.0,20*np.log10(max(rms,1)/32768)+90)*1.7)
            if self.on_level:self.on_level(level,rms)
            # Importante: por defecto NO usamos compuerta. Así no hace falta gritar.
            if not self._muted and not self._speaking and self.on_chunk:
                data=self._resample_bytes(raw.tobytes(),native,16000)
                self.on_chunk(data)
        self.input_stream=sd.InputStream(device=idx,samplerate=native,channels=1,dtype='int16',blocksize=block,callback=callback)
        self.input_stream.start(); self._running=True
        self.events.publish('audio.input.started',device=idx,name=sd.query_devices(idx)['name'],native_rate=native)
    def stop(self):
        self._running=False
        if self.input_stream:
            try:self.input_stream.stop(); self.input_stream.close()
            except Exception:pass
            self.input_stream=None
        if self.output_stream:
            try:self.output_stream.stop(); self.output_stream.close()
            except Exception:pass
            self.output_stream=None
    def restart(self,on_chunk=None,on_level=None): self.start(on_chunk or self.on_chunk,on_level or self.on_level)
    def play_pcm24(self,data:bytes):
        with self._output_lock:
            if self.output_stream is None:
                idx,native=self._resolve_output(); self._output_native_rate=native
                self.output_stream=sd.RawOutputStream(device=idx,samplerate=native,channels=1,dtype='int16',blocksize=0)
                self.output_stream.start(); self.events.publish('audio.output.started',device=idx,name=sd.query_devices(idx)['name'],native_rate=native)
            converted=self._resample_bytes(data,24000,self._output_native_rate)
            self.output_stream.write(converted)
    def record_test(self,seconds=4.0):
        idx,native=self._resolve_input(); frames=int(native*seconds)
        recording=sd.rec(frames,samplerate=native,channels=1,dtype='int16',device=idx); sd.wait()
        peak=int(np.max(np.abs(recording))) if recording.size else 0
        rms=float(np.sqrt(np.mean(recording.astype(np.float64)**2))) if recording.size else 0.0
        return recording,native,peak,rms
    def play_test(self,recording,rate): sd.play(recording,samplerate=rate); sd.wait()
