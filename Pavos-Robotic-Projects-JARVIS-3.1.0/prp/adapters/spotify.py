from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from prp.core.media_intelligence import MediaCandidate
from prp.core.models import ActionResult


SPOTIFY_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-library-modify",
    "user-library-read",
    "playlist-read-private",
    "playlist-read-collaborative",
])


class SpotifyAdapter:
    def __init__(self, registry, event_bus, config_getter, base_dir: Path):
        self.registry = registry
        self.event_bus = event_bus
        self.config_getter = config_getter
        self.base_dir = base_dir
        self._client_instance = None
        self._client_signature: tuple[str, str, str] | None = None
        self._client_lock = threading.RLock()
        self._playlist_cache: list[dict[str, Any]] = []
        self._playlist_cache_at = 0.0
        self._playlist_lock = threading.RLock()

    def register(self) -> None:
        r = self.registry.register_handler
        r("spotify.status", "Consulta la canción, dispositivo y estado actual de Spotify.", self.status, tags=("spotify", "media"))
        r("spotify.play_track", "Busca y reproduce una canción específica en Spotify.", self.play_track, tags=("spotify", "media"))
        r("spotify.play_playlist", "Busca y reproduce una playlist, priorizando la biblioteca del usuario.", self.play_playlist, tags=("spotify", "media"))
        r("spotify.play_artist", "Busca y reproduce música de un artista.", self.play_artist, tags=("spotify", "media"))
        r("spotify.play_album", "Busca y reproduce un álbum.", self.play_album, tags=("spotify", "media"))
        r("spotify.play_another_by_artist", "Reproduce otra canción del artista recordado.", self.play_another_by_artist, tags=("spotify", "media"))
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

        signature = (client_id, client_secret, redirect_uri)
        with self._client_lock:
            if self._client_instance is not None and self._client_signature == signature:
                return self._client_instance
            cache_path = str(self.base_dir / "config" / ".spotify_cache")
            auth = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=SPOTIFY_SCOPES,
                cache_path=cache_path,
                open_browser=True,
            )
            self._client_instance = spotipy.Spotify(
                auth_manager=auth,
                requests_timeout=10,
                retries=2,
                status_retries=2,
                backoff_factor=0.3,
            )
            self._client_signature = signature
            return self._client_instance

    def invalidate_client(self) -> None:
        with self._client_lock:
            self._client_instance = None
            self._client_signature = None
        with self._playlist_lock:
            self._playlist_cache = []
            self._playlist_cache_at = 0.0

    def _device(self, sp, params: dict[str, Any]) -> dict[str, Any] | None:
        requested = str(params.get("device", "") or self._config().get("preferred_device", "")).lower().strip()
        devices = [d for d in sp.devices().get("devices", []) if d]
        if requested:
            for device in devices:
                if requested in str(device.get("name", "")).lower() or requested == str(device.get("id", "")):
                    return device
        active = next((d for d in devices if d.get("is_active")), None)
        return active or (devices[0] if devices else None)

    def _device_id(self, sp, params: dict[str, Any]) -> str | None:
        device = self._device(sp, params)
        return str(device.get("id")) if device and device.get("id") else None

    def user_playlists(self, limit: int = 200, refresh: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        with self._playlist_lock:
            if not refresh and self._playlist_cache and time.monotonic() - self._playlist_cache_at < 300:
                return [dict(item) for item in self._playlist_cache[:limit]]

        sp = self._client()
        playlists: list[dict[str, Any]] = []
        offset = 0
        while len(playlists) < limit:
            page_size = min(50, limit - len(playlists))
            page = sp.current_user_playlists(limit=page_size, offset=offset) or {}
            items = [item for item in page.get("items", []) if item]
            for item in items:
                owner = item.get("owner") or {}
                playlists.append({
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "uri": item.get("uri", ""),
                    "owner": owner.get("display_name") or owner.get("id", ""),
                    "public": item.get("public"),
                    "collaborative": bool(item.get("collaborative")),
                    "tracks_total": (item.get("tracks") or {}).get("total"),
                    "external_url": (item.get("external_urls") or {}).get("spotify", ""),
                })
            offset += len(items)
            if not page.get("next") or not items:
                break

        with self._playlist_lock:
            self._playlist_cache = playlists
            self._playlist_cache_at = time.monotonic()
        return [dict(item) for item in playlists]

    def search_candidates(
        self,
        kind: str,
        query: str,
        *,
        artist: str = "",
        limit: int = 8,
    ) -> list[MediaCandidate]:
        kind = str(kind).lower().strip()
        if kind not in {"track", "playlist", "artist", "album"}:
            return []
        query = str(query or "").strip()
        if not query:
            return []
        sp = self._client()
        search_query = query
        if kind == "track" and artist:
            search_query = f'track:"{query}" artist:"{artist}"'
        try:
            result = sp.search(q=search_query, type=kind, limit=max(1, min(20, int(limit)))) or {}
        except Exception:
            if search_query != query:
                result = sp.search(q=query, type=kind, limit=max(1, min(20, int(limit)))) or {}
            else:
                raise
        key = {"track": "tracks", "playlist": "playlists", "artist": "artists", "album": "albums"}[kind]
        items = [item for item in (result.get(key) or {}).get("items", []) if item]
        candidates: list[MediaCandidate] = []
        for item in items:
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []) if a)
            owner_obj = item.get("owner") or {}
            candidates.append(MediaCandidate(
                type=kind,
                name=str(item.get("name", "")),
                uri=str(item.get("uri", "")),
                id=str(item.get("id", "")),
                source="spotify_catalog",
                score=0.0,
                artists=artists,
                owner=str(owner_obj.get("display_name") or owner_obj.get("id") or ""),
            ))
        return candidates

    def play_candidate(self, candidate: dict[str, Any], params: dict[str, Any]) -> ActionResult:
        kind = str(candidate.get("type", "track")).lower()
        uri = str(candidate.get("uri", "")).strip()
        name = str(candidate.get("name", "contenido")).strip()
        if not uri:
            return ActionResult.failure("La opción seleccionada no tiene URI de Spotify.")
        try:
            sp = self._client()
            device = self._device(sp, params)
            if not device:
                return ActionResult.failure(
                    "Spotify no reporta ningún dispositivo disponible. Abre Spotify y reproduce algo una vez."
                )
            device_id = device.get("id")
            if kind == "track":
                sp.start_playback(device_id=device_id, uris=[uri])
            else:
                sp.start_playback(device_id=device_id, context_uri=uri)
            artists = str(candidate.get("artists", ""))
            suffix = f" de {artists}" if artists else ""
            kind_es = {"playlist": "la playlist", "artist": "música de", "album": "el álbum", "track": ""}.get(kind, "")
            if kind == "artist":
                message = f"Reproduciendo música de {name}."
            elif kind == "track":
                message = f"Reproduciendo {name}{suffix}."
            else:
                message = f"Reproduciendo {kind_es} {name}."
            artist_uri = str(candidate.get("artist_uri", ""))
            return ActionResult.success(
                message,
                type=kind,
                name=name,
                track=name if kind == "track" else "",
                playlist=name if kind == "playlist" else "",
                artist=name if kind == "artist" else artists,
                artists=artists,
                uri=uri,
                artist_uri=artist_uri,
                source=candidate.get("source", "spotify"),
                device=device.get("name", ""),
                device_id=device_id,
            )
        except Exception as exc:
            return ActionResult.failure(
                f"No pude reproducir {name}: {exc}. El control de reproducción requiere Spotify Premium.",
                error=str(exc),
            )

    def status(self, _params: dict[str, Any]) -> ActionResult:
        try:
            current = self._client().current_playback()
            if not current:
                return ActionResult.success("Spotify no tiene reproducción activa.", active=False)
            item = current.get("item") or {}
            artists_list = [a for a in item.get("artists", []) if a]
            artists = ", ".join(a.get("name", "") for a in artists_list)
            device = current.get("device") or {}
            context = current.get("context") or {}
            data = {
                "active": True,
                "playing": bool(current.get("is_playing")),
                "type": "track",
                "name": item.get("name", ""),
                "track": item.get("name", ""),
                "artists": artists,
                "artist": artists,
                "artist_uri": artists_list[0].get("uri", "") if artists_list else "",
                "device": device.get("name", ""),
                "volume": device.get("volume_percent"),
                "uri": item.get("uri", ""),
                "context_uri": context.get("uri", ""),
                "context_type": context.get("type", ""),
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
            results = self.search_candidates("track", query, artist=str(params.get("artist", "")), limit=5)
            if not results:
                return ActionResult.failure(f"No encontré '{query}' en Spotify.")
            return self.play_candidate(results[0].to_dict(), params)
        except Exception as exc:
            return ActionResult.failure(f"No pude reproducir '{query}': {exc}. El control de reproducción requiere Spotify Premium.", error=str(exc))

    def play_playlist(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("playlist") or params.get("query") or "").strip()
        if not query:
            return ActionResult.failure("Falta el nombre de la playlist.")
        try:
            # Personal playlists first; the intelligence layer performs the full ranking.
            personal = self.user_playlists(limit=200)
            exact = next((p for p in personal if str(p.get("name", "")).casefold() == query.casefold()), None)
            if exact:
                return self.play_candidate({**exact, "type": "playlist", "source": "user_playlist"}, params)
            results = self.search_candidates("playlist", query, limit=5)
            if not results:
                return ActionResult.failure(f"No encontré la playlist '{query}'.")
            return self.play_candidate(results[0].to_dict(), params)
        except Exception as exc:
            return ActionResult.failure(f"No pude reproducir la playlist: {exc}. El control de reproducción requiere Spotify Premium.", error=str(exc))

    def play_artist(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("artist") or params.get("query") or "").strip()
        if not query:
            return ActionResult.failure("Falta el nombre del artista.")
        try:
            results = self.search_candidates("artist", query, limit=5)
            if not results:
                return ActionResult.failure(f"No encontré al artista '{query}'.")
            return self.play_candidate(results[0].to_dict(), params)
        except Exception as exc:
            return ActionResult.failure(f"No pude reproducir al artista: {exc}", error=str(exc))

    def play_album(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("album") or params.get("query") or "").strip()
        if not query:
            return ActionResult.failure("Falta el nombre del álbum.")
        try:
            results = self.search_candidates("album", query, artist=str(params.get("artist", "")), limit=5)
            if not results:
                return ActionResult.failure(f"No encontré el álbum '{query}'.")
            return self.play_candidate(results[0].to_dict(), params)
        except Exception as exc:
            return ActionResult.failure(f"No pude reproducir el álbum: {exc}", error=str(exc))

    def play_another_by_artist(self, params: dict[str, Any]) -> ActionResult:
        artist_query = str(params.get("artist") or params.get("query") or "").strip()
        if not artist_query:
            return ActionResult.failure("No tengo un artista de referencia.")
        exclude_uri = str(params.get("exclude_uri", ""))
        try:
            sp = self._client()
            artists = self.search_candidates("artist", artist_query, limit=5)
            if not artists:
                return ActionResult.failure(f"No encontré al artista '{artist_query}'.")
            artist = artists[0]
            try:
                top = sp.artist_top_tracks(artist.id) or {}
            except TypeError:
                top = sp.artist_top_tracks(artist.id, country="MX") or {}
            tracks = [track for track in top.get("tracks", []) if track and track.get("uri") != exclude_uri]
            if not tracks:
                return self.play_candidate(artist.to_dict(), params)
            track = tracks[0]
            candidate = {
                "type": "track",
                "name": track.get("name", ""),
                "uri": track.get("uri", ""),
                "artists": ", ".join(a.get("name", "") for a in track.get("artists", []) if a),
                "artist_uri": artist.uri,
                "source": "artist_top_tracks",
            }
            return self.play_candidate(candidate, params)
        except Exception as exc:
            return ActionResult.failure(f"No pude reproducir otra canción de {artist_query}: {exc}", error=str(exc))

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
            device = self._device(sp, params)
            if not device:
                return ActionResult.failure("Spotify no reporta ningún dispositivo disponible.")
            sp.volume(volume, device_id=device.get("id"))
            return ActionResult.success(
                f"Volumen de Spotify al {volume} %.",
                volume=volume,
                device=device.get("name", ""),
            )
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
