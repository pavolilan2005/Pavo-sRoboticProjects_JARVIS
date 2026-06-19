from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from .models import ActionResult
from .storage import JsonStore


DEFAULT_MEDIA_ALIASES: dict[str, Any] = {
    "version": 1,
    "aliases": [
        {
            "id": "stream",
            "phrases": ["stream", "musica para stream", "la del stream", "playlist del stream"],
            "type": "playlist",
            "target": "Stream",
            "uri": "",
            "volume": 22,
            "device": "",
            "enabled": True,
        },
        {
            "id": "estudio",
            "phrases": ["estudio", "programar", "musica para programar", "modo estudio"],
            "type": "playlist",
            "target": "Focus",
            "uri": "",
            "volume": 18,
            "device": "",
            "enabled": True,
        },
    ],
}

DEFAULT_MEDIA_STATE: dict[str, Any] = {
    "version": 1,
    "updated_at": 0.0,
    "current": {},
    "last_track": {},
    "last_artist": {},
    "last_playlist": {},
    "last_album": {},
    "last_context": {},
    "volume": None,
    "device": "",
}

TARGET_TYPES = {"auto", "alias", "track", "playlist", "artist", "album"}


@dataclass(slots=True)
class MediaCandidate:
    type: str
    name: str
    uri: str
    score: float
    source: str
    artists: str = ""
    owner: str = ""
    id: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["score"] = round(float(self.score), 4)
        return result


class MediaIntelligence:
    """Deterministic multimedia intent resolver and short-term context memory.

    Gemini decides *what the user is asking for*. This class decides *which exact
    Spotify object should be used*, prioritizing user aliases and personal
    playlists before the public catalogue.
    """

    def __init__(self, base_dir: Path, spotify, event_bus):
        self.base_dir = Path(base_dir)
        self.spotify = spotify
        self.event_bus = event_bus
        self.alias_store = JsonStore(
            self.base_dir / "config" / "media_aliases.json", DEFAULT_MEDIA_ALIASES
        )
        self.state_store = JsonStore(
            self.base_dir / "config" / "media_state.json", DEFAULT_MEDIA_STATE
        )
        self._lock = threading.RLock()

    # ----------------------------- public API -----------------------------
    def register(self, registry) -> None:
        register = registry.register_handler
        register(
            "media.smart_play",
            "Resuelve alias, playlists personales, canciones, artistas y álbumes antes de reproducir.",
            self.smart_play,
            tags=("media", "spotify", "intelligence"),
        )
        register(
            "media.context",
            "Consulta el contexto musical recordado por JARVIS.",
            lambda _params: self.context(),
            tags=("media", "intelligence"),
        )
        register(
            "media.context.clear",
            "Limpia el contexto musical temporal.",
            lambda _params: self.clear_context(),
            tags=("media", "intelligence"),
        )
        register(
            "media.aliases.list",
            "Lista los alias multimedia personales.",
            lambda _params: ActionResult.success(
                f"Hay {len(self.list_aliases())} alias multimedia.", aliases=self.list_aliases()
            ),
            tags=("media", "configuration"),
        )
        register(
            "media.playlists.list",
            "Lista las playlists propias y seguidas del usuario de Spotify.",
            self.list_spotify_playlists,
            tags=("media", "spotify", "configuration"),
        )

    def list_aliases(self) -> list[dict[str, Any]]:
        payload = self.alias_store.load()
        aliases = payload.get("aliases", []) if isinstance(payload, dict) else []
        return [dict(item) for item in aliases if isinstance(item, dict)]

    def replace_aliases(self, aliases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(aliases):
            item = self._clean_alias(raw, index)
            if not item["id"] or item["id"] in seen:
                raise ValueError(f"Alias multimedia duplicado o vacío: {item['id']!r}")
            seen.add(item["id"])
            cleaned.append(item)
        self.alias_store.save({"version": 1, "aliases": cleaned})
        self.event_bus.publish(
            "media.aliases.saved", {"count": len(cleaned)}, "media_intelligence"
        )
        return cleaned

    def upsert_alias(self, alias: dict[str, Any]) -> dict[str, Any]:
        aliases = self.list_aliases()
        item = self._clean_alias(alias, len(aliases))
        replaced = False
        for index, existing in enumerate(aliases):
            if existing.get("id") == item["id"]:
                aliases[index] = item
                replaced = True
                break
        if not replaced:
            aliases.append(item)
        self.replace_aliases(aliases)
        return item

    def delete_alias(self, alias_id: str) -> bool:
        alias_id = self._slug(alias_id)
        aliases = self.list_aliases()
        remaining = [item for item in aliases if self._slug(item.get("id", "")) != alias_id]
        if len(remaining) == len(aliases):
            return False
        self.replace_aliases(remaining)
        return True

    def context(self) -> ActionResult:
        state = self.state_store.load()
        current = state.get("current") or {}
        if not current:
            return ActionResult.success("No hay contexto musical guardado.", state=state)
        label = current.get("name") or current.get("target") or "contenido musical"
        artist = current.get("artists") or current.get("artist") or ""
        suffix = f" de {artist}" if artist else ""
        return ActionResult.success(
            f"Contexto musical actual: {label}{suffix}.", state=state
        )

    def clear_context(self) -> ActionResult:
        self.state_store.save(DEFAULT_MEDIA_STATE)
        self.event_bus.publish("media.context.cleared", {}, "media_intelligence")
        return ActionResult.success("Contexto musical limpiado.")

    def list_spotify_playlists(self, params: dict[str, Any]) -> ActionResult:
        limit = max(1, min(200, int(params.get("limit", 100))))
        try:
            playlists = self.spotify.user_playlists(limit=limit, refresh=bool(params.get("refresh", False)))
            return ActionResult.success(
                f"Encontré {len(playlists)} playlists propias o seguidas.",
                playlists=playlists,
            )
        except Exception as exc:
            return ActionResult.failure(f"No pude consultar tus playlists: {exc}", error=str(exc))

    def smart_play(self, params: dict[str, Any]) -> ActionResult:
        params = dict(params or {})
        query = self._first_text(
            params.get("query"),
            params.get("track"),
            params.get("playlist"),
            params.get("artist"),
            params.get("album"),
            params.get("alias"),
        )
        target_type = self._normalize_target_type(params.get("target_type", "auto"))
        relation = self._normalize(str(params.get("relation", ""))).replace(" ", "_")

        # Explicit fields always beat language heuristics.
        for field, kind in (
            ("alias", "alias"),
            ("playlist", "playlist"),
            ("track", "track"),
            ("artist", "artist"),
            ("album", "album"),
        ):
            if str(params.get(field, "")).strip():
                query = str(params[field]).strip()
                if target_type == "auto":
                    target_type = kind
                break

        contextual = self._resolve_context_request(query, relation, target_type, params)
        if contextual is not None:
            return contextual

        alias = self._match_alias(query, params.get("alias"))
        alias_type = self._normalize_target_type((alias or {}).get("type", "auto"))
        if alias and (target_type in {"auto", "alias"} or alias_type == target_type):
            return self._play_alias(alias, params)

        if target_type == "alias":
            names = ", ".join(a.get("id", "") for a in self.list_aliases() if a.get("enabled", True))
            return ActionResult.failure(
                f"No encontré el alias '{query}'. Alias disponibles: {names or 'ninguno'}.",
                error="media_alias_not_found",
            )

        if not query:
            return self.spotify.resume(params)

        inferred = target_type if target_type != "auto" else self._infer_target_type(query)
        return self._resolve_catalog_and_play(query, inferred, params)

    # ---------------------------- intent logic ----------------------------
    def _resolve_context_request(
        self,
        query: str,
        relation: str,
        target_type: str,
        params: dict[str, Any],
    ) -> ActionResult | None:
        norm = self._normalize(query)
        state = self.state_store.load()

        same_artist = relation in {"same_artist", "another_by_artist", "mismo_artista"} or any(
            phrase in norm
            for phrase in (
                "otra de ese artista",
                "otra del mismo artista",
                "otra de el",
                "otra de ella",
                "algo mas de ese artista",
                "otra cancion suya",
            )
        )
        if same_artist:
            artist = str(
                params.get("artist")
                or (state.get("last_artist") or {}).get("name")
                or (state.get("current") or {}).get("artists")
                or ""
            ).strip()
            if "," in artist:
                artist = artist.split(",", 1)[0].strip()
            if not artist:
                return ActionResult.failure(
                    "No recuerdo qué artista estabas escuchando.", error="media_context_missing_artist"
                )
            current_uri = str((state.get("current") or {}).get("uri", ""))
            result = self.spotify.play_another_by_artist(
                {**params, "artist": artist, "exclude_uri": current_uri}
            )
            return self._remember_result(result, "track", source="context_same_artist")

        previous_context = relation in {"last_context", "previous_context", "return"} or any(
            phrase in norm
            for phrase in (
                "regresa a la playlist",
                "vuelve a la playlist",
                "regresa a lo anterior",
                "vuelve a lo anterior",
            )
        )
        if previous_context:
            context = state.get("last_context") or state.get("last_playlist") or {}
            if not context:
                return ActionResult.failure(
                    "No recuerdo una playlist o contexto anterior.", error="media_context_missing"
                )
            return self._play_saved_context(context, params)

        if target_type == "auto" and norm in {"esa", "esa cancion", "la actual", "esta", "esta cancion"}:
            current = state.get("current") or {}
            if not current:
                return ActionResult.failure("No hay una canción actual en el contexto.")
            return self._play_saved_context(current, params)
        return None

    def _infer_target_type(self, query: str) -> str:
        norm = self._normalize(query)
        if any(token in norm for token in ("playlist", "lista", "mix", "mi musica para", "la del ")):
            return "playlist"
        if any(token in norm for token in ("album", "disco completo", "el disco")):
            return "album"
        if norm.startswith(("algo de ", "musica de ", "canciones de ", "pon a ", "reproduce a ")):
            return "artist"
        return "auto"

    def _resolve_catalog_and_play(
        self, query: str, target_type: str, params: dict[str, Any]
    ) -> ActionResult:
        artist_hint = str(params.get("artist", "")).strip()
        cleaned_query = self._strip_intent_words(query, target_type)
        candidates: list[MediaCandidate] = []

        types = [target_type] if target_type != "auto" else ["track", "playlist", "artist", "album"]
        for kind in types:
            if kind == "playlist":
                candidates.extend(self._playlist_candidates(cleaned_query))
            else:
                candidates.extend(self.spotify.search_candidates(kind, cleaned_query, artist=artist_hint, limit=8))

        ranked = self._rank_candidates(candidates, cleaned_query, artist_hint, target_type)
        if not ranked:
            return ActionResult.failure(
                f"No encontré una coincidencia para '{cleaned_query}'.",
                error="media_not_found",
                target_type=target_type,
            )

        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        threshold = 0.66 if target_type == "auto" else 0.58
        ambiguous = bool(
            second
            and (top.name.casefold() != second.name.casefold() or top.type != second.type or top.artists.casefold() != second.artists.casefold())
            and (top.score - second.score) < 0.075
        )
        if top.score < threshold or ambiguous:
            choices = ranked[:4]
            summary = "; ".join(self._candidate_label(c) for c in choices)
            return ActionResult.failure(
                f"Encontré varias opciones para '{cleaned_query}': {summary}. ¿Cuál quieres?",
                error="clarification_required",
                needs_clarification=True,
                candidates=[c.to_dict() for c in choices],
            )

        result = self.spotify.play_candidate(top.to_dict(), params)
        return self._remember_result(result, top.type, source=top.source)

    def _playlist_candidates(self, query: str) -> list[MediaCandidate]:
        items: list[MediaCandidate] = []
        try:
            for playlist in self.spotify.user_playlists(limit=200):
                items.append(
                    MediaCandidate(
                        type="playlist",
                        name=str(playlist.get("name", "")),
                        uri=str(playlist.get("uri", "")),
                        id=str(playlist.get("id", "")),
                        owner=str(playlist.get("owner", "")),
                        source="user_playlist",
                        score=self._similarity(query, str(playlist.get("name", ""))) + 0.13,
                    )
                )
        except Exception:
            pass
        items.extend(self.spotify.search_candidates("playlist", query, limit=8))
        return items

    def _rank_candidates(
        self,
        candidates: list[MediaCandidate],
        query: str,
        artist_hint: str,
        requested_type: str,
    ) -> list[MediaCandidate]:
        dedup: dict[str, MediaCandidate] = {}
        for candidate in candidates:
            if not candidate.uri:
                continue
            score = candidate.score or self._similarity(query, candidate.name)
            qnorm = self._normalize(query)
            nnorm = self._normalize(candidate.name)
            if qnorm == nnorm:
                score += 0.18
            elif nnorm.startswith(qnorm) or qnorm.startswith(nnorm):
                score += 0.08
            if candidate.source == "user_playlist":
                score += 0.08
            if requested_type != "auto" and candidate.type == requested_type:
                score += 0.05
            if artist_hint and candidate.artists:
                score += 0.18 * self._similarity(artist_hint, candidate.artists)
            candidate.score = min(1.25, score)
            existing = dedup.get(candidate.uri)
            if existing is None or candidate.score > existing.score:
                dedup[candidate.uri] = candidate
        return sorted(dedup.values(), key=lambda c: (-c.score, c.type, c.name.lower()))

    # ------------------------------ aliases -------------------------------
    def _match_alias(self, query: str, explicit_alias: Any = None) -> dict[str, Any] | None:
        wanted = self._normalize(str(explicit_alias or query))
        if not wanted:
            return None
        best: tuple[float, dict[str, Any]] | None = None
        for alias in self.list_aliases():
            if not alias.get("enabled", True):
                continue
            phrases = [alias.get("id", ""), alias.get("target", "")]
            phrases.extend(alias.get("phrases", []) or [])
            for phrase in phrases:
                pnorm = self._normalize(str(phrase))
                if not pnorm:
                    continue
                if wanted == pnorm:
                    return alias
                score = self._similarity(wanted, pnorm)
                if pnorm in wanted and len(pnorm) >= 4:
                    score += 0.18
                if best is None or score > best[0]:
                    best = (score, alias)
        return best[1] if best and best[0] >= 0.88 else None

    def _play_alias(self, alias: dict[str, Any], params: dict[str, Any]) -> ActionResult:
        kind = self._normalize_target_type(alias.get("type", "playlist"))
        target = str(alias.get("target", "")).strip()
        uri = str(alias.get("uri", "")).strip()
        merged = dict(params)
        if alias.get("device") and not merged.get("device"):
            merged["device"] = alias["device"]

        if uri:
            candidate = {
                "type": kind,
                "name": target or alias.get("id", "alias"),
                "uri": uri,
                "source": "alias_uri",
            }
            result = self.spotify.play_candidate(candidate, merged)
        else:
            result = self._resolve_catalog_and_play(target, kind, merged)

        if result.ok and alias.get("volume") not in (None, ""):
            volume_result = self.spotify.set_volume(
                {"volume": int(alias["volume"]), "device": merged.get("device", "")}
            )
            if not volume_result.ok:
                result.warnings.append(volume_result.message)
            else:
                result.data["volume"] = int(alias["volume"])
        if result.ok:
            result.data["alias"] = alias.get("id", "")
            self._remember_alias_context(alias, result)
        return result

    def _clean_alias(self, raw: dict[str, Any], index: int) -> dict[str, Any]:
        target = str(raw.get("target", "")).strip()
        alias_id = self._slug(raw.get("id") or target or f"alias_{index + 1}")
        phrases_raw = raw.get("phrases", [])
        if isinstance(phrases_raw, str):
            phrases = [p.strip() for p in re.split(r"[,;|]", phrases_raw) if p.strip()]
        else:
            phrases = [str(p).strip() for p in (phrases_raw or []) if str(p).strip()]
        if alias_id and alias_id not in [self._slug(p) for p in phrases]:
            phrases.insert(0, alias_id.replace("_", " "))
        kind = self._normalize_target_type(raw.get("type", "playlist"))
        if kind == "auto":
            kind = "playlist"
        volume = raw.get("volume")
        volume = None if volume in (None, "") else max(0, min(100, int(volume)))
        return {
            "id": alias_id,
            "phrases": phrases,
            "type": kind,
            "target": target,
            "uri": str(raw.get("uri", "")).strip(),
            "volume": volume,
            "device": str(raw.get("device", "")).strip(),
            "enabled": bool(raw.get("enabled", True)),
        }

    # ------------------------------ context -------------------------------
    def _remember_result(self, result: ActionResult, kind: str, source: str = "") -> ActionResult:
        if not result.ok:
            return result
        payload = dict(result.data or {})
        payload.setdefault("type", kind)
        payload.setdefault("source", source)
        payload["updated_at"] = time.time()

        def mutate(state: dict[str, Any]):
            state.setdefault("version", 1)
            state["updated_at"] = time.time()
            state["current"] = payload
            if kind == "track":
                state["last_track"] = payload
                artist_name = payload.get("artists") or payload.get("artist")
                artist_uri = payload.get("artist_uri", "")
                if artist_name:
                    state["last_artist"] = {"name": artist_name, "uri": artist_uri}
            elif kind == "playlist":
                state["last_playlist"] = payload
                state["last_context"] = payload
            elif kind == "artist":
                state["last_artist"] = payload
                state["last_context"] = payload
            elif kind == "album":
                state["last_album"] = payload
                state["last_context"] = payload
            if payload.get("volume") is not None:
                state["volume"] = payload.get("volume")
            if payload.get("device"):
                state["device"] = payload.get("device")
            return state

        self.state_store.update(mutate)
        self.event_bus.publish("media.context.updated", payload, "media_intelligence")
        return result

    def _remember_alias_context(self, alias: dict[str, Any], result: ActionResult) -> None:
        def mutate(state: dict[str, Any]):
            current = dict(state.get("current") or {})
            current["alias"] = alias.get("id", "")
            state["current"] = current
            if alias.get("type") in {"playlist", "artist", "album"}:
                state["last_context"] = current
            return state
        self.state_store.update(mutate)

    def _play_saved_context(self, context: dict[str, Any], params: dict[str, Any]) -> ActionResult:
        uri = str(context.get("uri", ""))
        kind = self._normalize_target_type(context.get("type", "auto"))
        name = str(context.get("name") or context.get("playlist") or context.get("track") or "contexto anterior")
        if uri:
            result = self.spotify.play_candidate(
                {"type": kind, "name": name, "uri": uri, "artists": context.get("artists", ""), "source": "saved_context"},
                params,
            )
            return self._remember_result(result, kind, source="saved_context")
        return self._resolve_catalog_and_play(name, kind, params)

    # ------------------------------ helpers -------------------------------
    @staticmethod
    def _normalize(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _slug(cls, value: Any) -> str:
        return cls._normalize(str(value)).replace(" ", "_")

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        a = cls._normalize(left)
        b = cls._normalize(right)
        if not a or not b:
            return 0.0
        seq = SequenceMatcher(None, a, b).ratio()
        aset, bset = set(a.split()), set(b.split())
        token = len(aset & bset) / max(1, len(aset | bset))
        containment = min(len(a), len(b)) / max(len(a), len(b)) if a in b or b in a else 0.0
        return 0.55 * seq + 0.30 * token + 0.15 * containment

    @classmethod
    def _normalize_target_type(cls, value: Any) -> str:
        raw = cls._normalize(str(value or "auto"))
        aliases = {
            "cancion": "track", "song": "track", "track": "track",
            "lista": "playlist", "lista de reproduccion": "playlist", "playlist": "playlist",
            "artista": "artist", "artist": "artist",
            "album": "album", "disco": "album",
            "alias": "alias", "auto": "auto", "automatico": "auto",
        }
        result = aliases.get(raw, raw)
        return result if result in TARGET_TYPES else "auto"

    @classmethod
    def _strip_intent_words(cls, query: str, kind: str) -> str:
        text = str(query or "").strip()
        patterns = [
            r"^(pon|reproduce|toca|quiero escuchar|escuchar)\s+",
            r"^(mi|la|el)\s+(playlist|lista|album|disco)\s+((de|del)\s+)?",
            r"^(playlist|lista|album|disco|cancion)\s+((de|del)\s+)?",
            r"^(la|el)\s+del?\s+",
            r"^(algo|musica|canciones)\s+de\s+" if kind == "artist" else r"$^",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        return text or str(query or "").strip()

    @staticmethod
    def _first_text(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _candidate_label(candidate: MediaCandidate) -> str:
        extra = f" de {candidate.artists}" if candidate.artists else ""
        source = "tu playlist" if candidate.source == "user_playlist" else candidate.type
        return f"{candidate.name}{extra} ({source})"
