from __future__ import annotations

from pathlib import Path
from typing import Any

from prp_core.models import ActionResult


SPOTIFY_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-library-modify",
    "playlist-read-private",
])


class SpotifyAdapter:
    def __init__(self, registry, event_bus, config_getter, base_dir: Path):
        self.registry = registry
        self.event_bus = event_bus
        self.config_getter = config_getter
        self.base_dir = base_dir

    def register(self) -> None:
        r = self.registry.register_handler
        r("spotify.status", "Consulta la canción, dispositivo y estado actual de Spotify.", self.status, tags=("spotify", "media"))
        r("spotify.play_track", "Busca y reproduce una canción específica en Spotify.", self.play_track, tags=("spotify", "media"))
        r("spotify.play_playlist", "Busca y reproduce una playlist de Spotify.", self.play_playlist, tags=("spotify", "media"))
        r("spotify.resume", "Reanuda Spotify.", self.resume, tags=("spotify", "media"))
        r("spotify.pause", "Pausa Spotify.", self.pause, tags=("spotify", "media"))
        r("spotify.next", "Siguiente canción en Spotify.", self.next, tags=("spotify", "media"))
        r("spotify.previous", "Canción anterior en Spotify.", self.previous, tags=("spotify", "media"))
        r("spotify.set_volume", "Ajusta el volumen de Spotify entre 0 y 100.", self.set_volume, tags=("spotify", "media"))
        r("spotify.save_current", "Guarda la canción actual en la biblioteca.", self.save_current, tags=("spotify", "media"))

    def _config(self) -> dict[str, Any]:
        return dict(self.config_getter().get("spotify") or {})

    def _client(self):
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
        except ImportError as exc:
            raise RuntimeError("Falta spotipy. Ejecuta INSTALAR_JARVIS.bat nuevamente.") from exc
        cfg = self._config()
        client_id = str(cfg.get("client_id", "")).strip()
        client_secret = str(cfg.get("client_secret", "")).strip()
        redirect_uri = str(cfg.get("redirect_uri", "http://127.0.0.1:8888/callback")).strip()
        if not client_id or not client_secret:
            raise RuntimeError("Spotify no está configurado en el Centro de Control.")
        cache_path = str(self.base_dir / "config" / ".spotify_cache")
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            cache_path=cache_path,
            open_browser=True,
        )
        return spotipy.Spotify(auth_manager=auth, requests_timeout=10, retries=2)

    def _device_id(self, sp, params: dict[str, Any]) -> str | None:
        requested = str(params.get("device", "") or self._config().get("preferred_device", "")).lower().strip()
        devices = sp.devices().get("devices", [])
        if requested:
            for device in devices:
                if requested in str(device.get("name", "")).lower() or requested == str(device.get("id", "")):
                    return device.get("id")
        active = next((d for d in devices if d.get("is_active")), None)
        return (active or (devices[0] if devices else {})).get("id")

    def status(self, _params: dict[str, Any]) -> ActionResult:
        try:
            current = self._client().current_playback()
            if not current:
                return ActionResult.success("Spotify no tiene reproducción activa.", active=False)
            item = current.get("item") or {}
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
            device = current.get("device") or {}
            data = {
                "active": True,
                "playing": bool(current.get("is_playing")),
                "track": item.get("name", ""),
                "artists": artists,
                "device": device.get("name", ""),
                "volume": device.get("volume_percent"),
                "uri": item.get("uri", ""),
            }
            return ActionResult.success(
                f"Spotify {'reproduce' if data['playing'] else 'tiene pausada'} {data['track']} de {artists}.",
                **data,
            )
        except Exception as exc:
            return ActionResult.failure(f"No pude consultar Spotify: {exc}", error=str(exc))

    def play_track(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("query") or params.get("track") or "").strip()
        if not query:
            return ActionResult.failure("Falta el nombre de la canción.")
        try:
            sp = self._client()
            results = sp.search(q=query, type="track", limit=5).get("tracks", {}).get("items", [])
            if not results:
                return ActionResult.failure(f"No encontré '{query}' en Spotify.")
            track = results[0]
            device_id = self._device_id(sp, params)
            if not device_id:
                return ActionResult.failure("Spotify no reporta ningún dispositivo disponible. Abre Spotify y reproduce algo una vez.")
            sp.start_playback(device_id=device_id, uris=[track["uri"]])
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            return ActionResult.success(f"Reproduciendo {track['name']} de {artists}.", track=track["name"], artists=artists, uri=track["uri"])
        except Exception as exc:
            return ActionResult.failure(f"No pude reproducir '{query}': {exc}. El control de reproducción requiere Spotify Premium.", error=str(exc))

    def play_playlist(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("playlist") or params.get("query") or "").strip()
        if not query:
            return ActionResult.failure("Falta el nombre de la playlist.")
        try:
            sp = self._client()
            results = sp.search(q=query, type="playlist", limit=5).get("playlists", {}).get("items", [])
            results = [item for item in results if item]
            if not results:
                return ActionResult.failure(f"No encontré la playlist '{query}'.")
            playlist = results[0]
            device_id = self._device_id(sp, params)
            if not device_id:
                return ActionResult.failure("Spotify no reporta un dispositivo disponible.")
            sp.start_playback(device_id=device_id, context_uri=playlist["uri"])
            return ActionResult.success(f"Reproduciendo la playlist {playlist['name']}.", playlist=playlist["name"], uri=playlist["uri"])
        except Exception as exc:
            return ActionResult.failure(f"No pude reproducir la playlist: {exc}. El control de reproducción requiere Spotify Premium.", error=str(exc))

    def resume(self, params: dict[str, Any]) -> ActionResult:
        try:
            sp = self._client()
            sp.start_playback(device_id=self._device_id(sp, params))
            return ActionResult.success("Spotify reanudado.")
        except Exception as exc:
            return ActionResult.failure(f"No pude reanudar Spotify: {exc}")

    def pause(self, params: dict[str, Any]) -> ActionResult:
        try:
            sp = self._client()
            sp.pause_playback(device_id=self._device_id(sp, params))
            return ActionResult.success("Spotify pausado.")
        except Exception as exc:
            return ActionResult.failure(f"No pude pausar Spotify: {exc}")

    def next(self, params: dict[str, Any]) -> ActionResult:
        try:
            sp = self._client()
            sp.next_track(device_id=self._device_id(sp, params))
            return ActionResult.success("Siguiente canción.")
        except Exception as exc:
            return ActionResult.failure(f"No pude cambiar de canción: {exc}")

    def previous(self, params: dict[str, Any]) -> ActionResult:
        try:
            sp = self._client()
            sp.previous_track(device_id=self._device_id(sp, params))
            return ActionResult.success("Canción anterior.")
        except Exception as exc:
            return ActionResult.failure(f"No pude regresar de canción: {exc}")

    def set_volume(self, params: dict[str, Any]) -> ActionResult:
        try:
            volume = max(0, min(100, int(params.get("volume", 50))))
            sp = self._client()
            sp.volume(volume, device_id=self._device_id(sp, params))
            return ActionResult.success(f"Volumen de Spotify al {volume} %.", volume=volume)
        except Exception as exc:
            return ActionResult.failure(f"No pude ajustar Spotify: {exc}")

    def save_current(self, _params: dict[str, Any]) -> ActionResult:
        try:
            sp = self._client()
            current = sp.current_playback() or {}
            item = current.get("item") or {}
            track_id = item.get("id")
            if not track_id:
                return ActionResult.failure("No hay una canción activa para guardar.")
            sp.current_user_saved_tracks_add([track_id])
            return ActionResult.success(f"Guardé {item.get('name', 'la canción')} en tu biblioteca.")
        except Exception as exc:
            return ActionResult.failure(f"No pude guardar la canción: {exc}")
