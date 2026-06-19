from prp.core.capabilities import Result
class OBSService:
    def __init__(self,config): self.config=config
    def _client(self):
        import obsws_python as obs
        cfg=(self.config.load('integrations.json',{}) or {}).get('obs',{}); sec=self.config.secrets()
        return obs.ReqClient(host=cfg.get('host','127.0.0.1'),port=int(cfg.get('port',4455)),password=sec.get('obs_password',''),timeout=4)
    def status(self):
        try:self._client().get_version(); return Result(True,'OBS WebSocket conectado')
        except Exception as e:return Result(False,f'OBS: {e}')
    def set_scene(self,scene):
        try:self._client().set_current_program_scene(scene); return Result(True,f'Escena activa: {scene}')
        except Exception as e:return Result(False,f'No pude cambiar escena: {e}')
