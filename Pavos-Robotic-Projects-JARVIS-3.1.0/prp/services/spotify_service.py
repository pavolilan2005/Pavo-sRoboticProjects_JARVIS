from __future__ import annotations
from typing import Any
from prp.core.config import ConfigStore
from prp.core.models import ActionResult

SCOPES = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative user-library-modify user-library-read"

class SpotifyService:
    def __init__(self, config: ConfigStore):
        self.config = config
        self._spotify = None
    def _client(self):
        if self._spotify is not None: return self._spotify
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        secrets = self.config.secrets()
        cfg = (self.config.load("integrations.json", {}) or {}).get("spotify", {})
        self._spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=secrets.get("spotify_client_id"), client_secret=secrets.get("spotify_client_secret"), redirect_uri=cfg.get("redirect_uri", "http://127.0.0.1:8888/callback"), scope=SCOPES, cache_path=str(self.config.path(".spotify_cache")), open_browser=True))
        return self._spotify
    def _device(self) -> str | None:
        cfg = (self.config.load("integrations.json", {}) or {}).get("spotify", {})
        preferred = str(cfg.get("preferred_device", "")).lower().strip()
        devices = self._client().devices().get("devices", [])
        if preferred:
            match = next((d for d in devices if preferred in d.get("name", "").lower()), None)
            if match: return match["id"]
        active = next((d for d in devices if d.get("is_active")), None)
        return active["id"] if active else (devices[0]["id"] if devices else None)
    def status(self) -> ActionResult:
        try:
            state = self._client().current_playback()
            if not state: return ActionResult.success("Spotify conectado, sin reproducción activa")
            item = state.get("item") or {}
            return ActionResult.success(f"Spotify: {item.get('name', 'sin título')}", playing=state.get("is_playing", False), track=item.get("name"), artist=", ".join(a["name"] for a in item.get("artists", [])))
        except Exception as exc: return ActionResult.failure("Spotify no disponible", str(exc))
    def play(self, query: str, kind: str = "track") -> ActionResult:
        try:
            sp = self._client(); device = self._device()
            search_type = kind if kind in {"track", "artist", "album", "playlist"} else "track"
            result = sp.search(q=query, type=search_type, limit=5)
            items = result.get(search_type + "s", {}).get("items", [])
            if not items: return ActionResult.failure(f"No encontré {query}")
            item = items[0]
            if search_type == "track": sp.start_playback(device_id=device, uris=[item["uri"]])
            else: sp.start_playback(device_id=device, context_uri=item["uri"])
            return ActionResult.success(f"Reproduciendo {item['name']}", uri=item["uri"], type=search_type)
        except Exception as exc: return ActionResult.failure("No pude reproducir en Spotify", str(exc))
    def play_alias(self, alias: str) -> ActionResult:
        aliases = (self.config.load("media_aliases.json", {}) or {}).get("aliases", [])
        needle = alias.lower().strip()
        item = next((a for a in aliases if needle == str(a.get("id", "")).lower() or needle in [str(x).lower() for x in a.get("phrases", [])]), None)
        if not item: return ActionResult.failure(f"Alias multimedia no encontrado: {alias}")
        try:
            sp = self._client(); device = self._device(); uri = item.get("uri")
            if uri:
                if item.get("type") == "track": sp.start_playback(device_id=device, uris=[uri])
                else: sp.start_playback(device_id=device, context_uri=uri)
                return ActionResult.success(f"Reproduciendo alias {alias}")
            return self.play(str(item.get("target", alias)), str(item.get("type", "playlist")))
        except Exception as exc: return ActionResult.failure("No pude reproducir el alias", str(exc))
    def pause(self) -> ActionResult:
        try: self._client().pause_playback(device_id=self._device()); return ActionResult.success("Música en pausa")
        except Exception as exc: return ActionResult.failure("No pude pausar", str(exc))
    def volume(self, volume: int) -> ActionResult:
        try:
            value = max(0, min(100, int(volume))); self._client().volume(value, device_id=self._device()); return ActionResult.success(f"Spotify al {value}%")
        except Exception as exc: return ActionResult.failure("No pude ajustar volumen", str(exc))
