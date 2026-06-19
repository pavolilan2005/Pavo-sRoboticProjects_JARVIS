from prp.core.capabilities import Result
class SpotifyService:
    SCOPES='user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative user-library-modify user-library-read'
    def __init__(self,config): self.config=config; self._sp=None
    def _client(self):
        if self._sp:return self._sp
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        sec=self.config.secrets(); cfg=(self.config.load('integrations.json',{}) or {}).get('spotify',{})
        if not sec.get('spotify_client_id') or not sec.get('spotify_client_secret'): raise RuntimeError('Spotify no está configurado')
        cache=str(self.config.root/cfg.get('cache_path','config/.spotify_cache'))
        auth=SpotifyOAuth(client_id=sec['spotify_client_id'],client_secret=sec['spotify_client_secret'],redirect_uri=sec.get('spotify_redirect_uri','http://127.0.0.1:8888/callback'),scope=self.SCOPES,cache_path=cache,open_browser=True)
        self._sp=spotipy.Spotify(auth_manager=auth); return self._sp
    def play(self,query,target_type='track'):
        try:
            sp=self._client(); kind={'track':'track','playlist':'playlist','artist':'artist','album':'album'}.get(target_type,'track')
            res=sp.search(q=query,type=kind,limit=1); item=res[kind+'s']['items'][0]
            if kind=='track':sp.start_playback(uris=[item['uri']])
            else:sp.start_playback(context_uri=item['uri'])
            return Result(True,f'Reproduciendo {item["name"]}')
        except Exception as e:return Result(False,f'Spotify: {e}')
    def play_alias(self,alias):
        aliases=(self.config.load('media_aliases.json',{}) or {}).get('aliases',[]); key=alias.lower().strip()
        item=next((a for a in aliases if key==str(a.get('id','')).lower() or key in [str(x).lower() for x in a.get('phrases',[])]),None)
        if not item:return Result(False,f'Alias multimedia no encontrado: {alias}')
        try:
            sp=self._client(); uri=item.get('uri')
            if uri: sp.start_playback(uris=[uri] if item.get('type')=='track' else None,context_uri=None if item.get('type')=='track' else uri); return Result(True,f'Reproduciendo {alias}')
            return self.play(item.get('target',''),item.get('type','playlist'))
        except Exception as e:return Result(False,f'Spotify: {e}')
    def pause(self):
        try:self._client().pause_playback();return Result(True,'Música pausada')
        except Exception as e:return Result(False,f'Spotify: {e}')
    def resume(self):
        try:self._client().start_playback();return Result(True,'Música reanudada')
        except Exception as e:return Result(False,f'Spotify: {e}')
    def next(self):
        try:self._client().next_track();return Result(True,'Siguiente canción')
        except Exception as e:return Result(False,f'Spotify: {e}')
