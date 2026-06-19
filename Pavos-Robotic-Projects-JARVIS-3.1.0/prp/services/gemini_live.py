from __future__ import annotations
import asyncio,re,time,traceback
from google import genai
from google.genai import types

class GeminiLiveService:
    def __init__(self,controller,callbacks):
        self.controller=controller; self.cb=callbacks; self.session=None; self.loop=None
        self.mic_queue=asyncio.Queue(maxsize=80); self.play_queue=asyncio.Queue()
        self.running=False; self.awake_until=0.0; self.authorized=False; self.pending_audio=[]
        app=controller.config.load('app.json',{}) or {}; self.settings=app
    def push_mic(self,data:bytes):
        if not self.loop:return
        def put():
            if self.mic_queue.full():
                try:self.mic_queue.get_nowait()
                except:pass
            try:self.mic_queue.put_nowait(data)
            except:pass
        self.loop.call_soon_threadsafe(put)
    def _wake(self):
        seconds=float(self.settings.get('assistant',{}).get('followup_seconds',30)); self.awake_until=time.monotonic()+seconds; self.authorized=True; self.cb.state('LISTENING')
    def _is_awake(self): return time.monotonic()<self.awake_until
    def _has_wake(self,text):
        norm=re.sub(r'[^a-záéíóúñ ]',' ',text.lower()); return any(w in norm for w in self.settings.get('assistant',{}).get('wake_words',['jarvis']))
    def config(self):
        tools=[{'function_declarations':[
            {'name':'open_app','description':'Abre una aplicación','parameters':{'type':'OBJECT','properties':{'name':{'type':'STRING'}},'required':['name']}},
            {'name':'play_music','description':'Reproduce canción, artista, álbum o playlist','parameters':{'type':'OBJECT','properties':{'query':{'type':'STRING'},'target_type':{'type':'STRING'}},'required':['query']}},
            {'name':'play_media_alias','description':'Reproduce un alias multimedia personal','parameters':{'type':'OBJECT','properties':{'alias':{'type':'STRING'}},'required':['alias']}},
            {'name':'media_control','description':'Controla Spotify','parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING'}},'required':['action']}},
            {'name':'run_routine','description':'Ejecuta una rutina','parameters':{'type':'OBJECT','properties':{'routine_id':{'type':'STRING'}},'required':['routine_id']}},
            {'name':'set_home_device','description':'Controla un dispositivo domótico','parameters':{'type':'OBJECT','properties':{'device':{'type':'STRING'},'state':{'type':'STRING'}},'required':['device','state']}},
            {'name':'obs_scene','description':'Cambia la escena de OBS','parameters':{'type':'OBJECT','properties':{'scene':{'type':'STRING'}},'required':['scene']}}
        ]}]
        prompt="Eres JARVIS, asistente de Pavo's Robotic Projects. Responde en español, breve y natural. Para audio del micrófono, solo responde o llames herramientas cuando la frase incluya Jarvis o sea un seguimiento inmediato de una conversación activa. No afirmes que ejecutaste algo sin usar una herramienta. Interpreta claramente canción vs artista vs playlist."
        return types.LiveConnectConfig(response_modalities=['AUDIO'],input_audio_transcription={},output_audio_transcription={},system_instruction=prompt,tools=tools,speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.settings.get('gemini',{}).get('voice','Charon')))))
    async def send_text(self,text):
        if self.session:
            self._wake(); await self.session.send_realtime_input(text=text)
    async def _send_mic(self):
        while True:
            data=await self.mic_queue.get()
            await self.session.send_realtime_input(audio=types.Blob(data=data,mime_type='audio/pcm;rate=16000'))
    async def _execute_tool(self,fc):
        args=dict(fc.args or {}); mapping={'open_app':('pc.open_app',{'name':args.get('name','')}),'play_music':('spotify.play',{'query':args.get('query',''),'target_type':args.get('target_type','track')}),'play_media_alias':('spotify.play_alias',{'alias':args.get('alias','')}),'run_routine':('routine.run',{'routine_id':args.get('routine_id','')}),'set_home_device':('home.set',{'device':args.get('device',''),'state':args.get('state','on')}),'obs_scene':('obs.set_scene',{'scene':args.get('scene','')})}
        if fc.name=='media_control':
            cap={'pause':'spotify.pause','resume':'spotify.resume','play':'spotify.resume','next':'spotify.next'}.get(str(args.get('action','')).lower(),'spotify.resume'); params={}
        else: cap,params=mapping.get(fc.name,('',{}))
        result=await self.controller.execute(cap,params)
        return types.FunctionResponse(id=fc.id,name=fc.name,response={'result':result.message,'ok':result.ok})
    async def _receive(self):
        inbuf=[]; outbuf=[]
        while True:
            async for response in self.session.receive():
                if response.server_content:
                    sc=response.server_content
                    if sc.input_transcription and sc.input_transcription.text:
                        txt=sc.input_transcription.text.strip(); inbuf.append(txt)
                        if self._has_wake(txt) or self._is_awake(): self._wake(); self._flush_pending()
                    if sc.output_transcription and sc.output_transcription.text: outbuf.append(sc.output_transcription.text.strip())
                    if sc.model_turn:
                        for part in sc.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                if self.authorized or self._is_awake(): self.play_queue.put_nowait(part.inline_data.data)
                                else:
                                    self.pending_audio.append(part.inline_data.data); self.pending_audio=self.pending_audio[-180:]
                    if sc.turn_complete:
                        fullin=' '.join(inbuf).strip(); fullout=' '.join(outbuf).strip()
                        allowed=self.authorized or self._has_wake(fullin) or self._is_awake()
                        if allowed:
                            if fullin:self.cb.transcript('TÚ',fullin)
                            if fullout:self.cb.transcript('JARVIS',fullout)
                        else:self.pending_audio.clear()
                        inbuf.clear();outbuf.clear();self.authorized=False
                if response.tool_call:
                    replies=[]
                    for fc in response.tool_call.function_calls:
                        if self.authorized or self._is_awake(): replies.append(await self._execute_tool(fc))
                        else: replies.append(types.FunctionResponse(id=fc.id,name=fc.name,response={'result':'ignored_sleeping','ok':False}))
                    await self.session.send_tool_response(function_responses=replies)
    def _flush_pending(self):
        for b in self.pending_audio:self.play_queue.put_nowait(b)
        self.pending_audio.clear()
    async def _play(self):
        while True:
            data=await self.play_queue.get(); self.controller.audio.set_speaking(True); self.cb.state('SPEAKING')
            await asyncio.to_thread(self.controller.audio.play_pcm24,data)
            if self.play_queue.empty(): self.controller.audio.set_speaking(False); self.awake_until=time.monotonic()+float(self.settings.get('assistant',{}).get('followup_seconds',30)); self.cb.state('LISTENING')
    async def run(self):
        self.loop=asyncio.get_running_loop(); self.running=True
        key=self.controller.config.secrets().get('gemini_api_key','')
        if not key: self.cb.log('Falta config/secrets.json con gemini_api_key'); return
        client=genai.Client(api_key=key)
        delay=1
        while self.running:
            try:
                self.cb.state('CONNECTING')
                async with client.aio.live.connect(model=self.settings.get('gemini',{}).get('model','gemini-3.1-flash-live-preview'),config=self.config()) as session:
                    self.session=session; self.cb.log('JARVIS online. Di Jarvis con voz normal.'); self.cb.state('SLEEPING'); delay=1
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._send_mic()); tg.create_task(self._receive()); tg.create_task(self._play())
            except ExceptionGroup as eg:
                for e in eg.exceptions:self.cb.log(f'Error de sesión: {type(e).__name__}: {e}')
            except Exception as e:self.cb.log(f'Error de sesión: {type(e).__name__}: {e}')
            self.session=None
            if self.running: self.cb.log(f'Reconectando en {delay}s...'); await asyncio.sleep(delay); delay=min(20,delay*2)
