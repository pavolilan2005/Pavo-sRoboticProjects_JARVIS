from __future__ import annotations

import json
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

import requests

from prp_core.models import ActionResult
from prp_core.storage import JsonStore


DEFAULT_MAP_CONFIG = {
    "version": 1,
    "language": "es",
    "search_limit": 5,
    "default_view": {
        "name": "México",
        "lat": 23.6345,
        "lon": -102.5528,
        "height": 11_500_000,
    },
    "home": {
        "name": "",
        "lat": None,
        "lon": None,
        "height": 18_000,
    },
}

DEFAULT_LOCATIONS = {"version": 1, "locations": []}


class NavigationAdapter:
    """Geocoding and UI bridge for PRP Holographic Navigation.

    The adapter owns network geocoding, caching and saved locations. The Qt map
    owns rendering only. Nominatim calls are throttled to one request per second
    and cached locally to comply with the public service's light-use policy.
    """

    SEARCH_URL = "https://nominatim.openstreetmap.org/search"
    REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

    def __init__(self, registry, event_bus, base_dir: str | Path, ui=None):
        self.registry = registry
        self.event_bus = event_bus
        self.base_dir = Path(base_dir)
        self.ui = ui
        self.config_store = JsonStore(self.base_dir / "config" / "map.json", DEFAULT_MAP_CONFIG)
        self.locations_store = JsonStore(self.base_dir / "config" / "locations.json", DEFAULT_LOCATIONS)
        self.cache_store = JsonStore(self.base_dir / "config" / "map_cache.json", {"version": 1, "search": {}, "reverse": {}})
        self._request_lock = threading.RLock()
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "PavosRoboticProjects-JARVIS/3.2.0 (personal holographic navigation)",
            "Accept": "application/json",
        })
        self._current: dict[str, Any] = {}

    def register(self) -> None:
        r = self.registry.register_handler
        r("map.open", "Abre el sistema holográfico de navegación.", self.open_map, tags=("map", "navigation"))
        r("map.search", "Busca un lugar y navega hasta él.", self.search, tags=("map", "navigation"), timeout_seconds=18)
        r("map.fly_to", "Mueve la cámara a coordenadas o a un lugar.", self.fly_to, tags=("map", "navigation"), timeout_seconds=18)
        r("map.home", "Navega a la ubicación principal configurada.", self.home, tags=("map", "navigation"))
        r("map.global", "Regresa a la vista global.", self.global_view, tags=("map", "navigation"))
        r("map.save", "Guarda una ubicación con un nombre.", self.save_location, tags=("map", "navigation"))
        r("map.set_home", "Configura la ubicación principal del mapa.", self.set_home, tags=("map", "navigation"))
        r("map.saved", "Lista ubicaciones guardadas.", self.list_saved, tags=("map", "navigation"))
        r("map.reverse", "Identifica coordenadas seleccionadas.", self.reverse, tags=("map", "navigation"), timeout_seconds=18)
        r("map.clear", "Limpia los marcadores del mapa.", self.clear_markers, tags=("map", "navigation"))
        r("map.status", "Devuelve el objetivo y configuración actual del mapa.", self.status, tags=("map", "navigation"))

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(text or "").lower())
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).strip()

    def _config(self) -> dict[str, Any]:
        raw = self.config_store.load()
        merged = json.loads(json.dumps(DEFAULT_MAP_CONFIG))
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
        return merged

    def _ui(self, method: str, *args) -> None:
        if not self.ui or not hasattr(self.ui, method):
            return
        try:
            getattr(self.ui, method)(*args)
        except Exception:
            pass

    def _throttled_get(self, url: str, params: dict[str, Any]) -> Any:
        with self._request_lock:
            wait = 1.05 - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            response = self._session.get(url, params=params, timeout=12)
            self._last_request = time.monotonic()
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _height_for(item: dict[str, Any]) -> float:
        place_type = str(item.get("type") or item.get("addresstype") or "").lower()
        category = str(item.get("category") or "").lower()
        if place_type in {"country", "continent"}:
            return 2_600_000
        if place_type in {"state", "region", "province"}:
            return 850_000
        if place_type in {"county", "municipality"}:
            return 260_000
        if place_type in {"city", "town"}:
            return 75_000
        if place_type in {"village", "suburb", "neighbourhood"}:
            return 25_000
        if category in {"tourism", "historic", "amenity", "building"}:
            return 3_500
        return 18_000

    def _format_result(self, raw: dict[str, Any]) -> dict[str, Any]:
        display = str(raw.get("display_name") or "Ubicación")
        name = str(raw.get("name") or display.split(",", 1)[0]).strip()
        item = {
            "name": name,
            "display_name": display,
            "lat": float(raw["lat"]),
            "lon": float(raw["lon"]),
            "type": str(raw.get("type") or raw.get("addresstype") or "lugar"),
            "category": str(raw.get("category") or raw.get("class") or "place"),
            "importance": float(raw.get("importance") or 0.0),
            "height": self._height_for(raw),
            "address": dict(raw.get("address") or {}),
        }
        return item

    def open_map(self, _params: dict[str, Any] | None = None) -> ActionResult:
        self._ui("open_map")
        self.event_bus.publish("map.opened", {}, "navigation")
        return ActionResult.success("Abrí el sistema holográfico de navegación.")

    def search(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("query") or params.get("place") or params.get("location") or "").strip()
        if not query:
            return ActionResult.failure("Falta el lugar que quieres buscar.", error="missing_query")

        config = self._config()
        cache = self.cache_store.load()
        search_cache = cache.setdefault("search", {})
        key = self._normalize(query)
        raw_results = search_cache.get(key)

        if not isinstance(raw_results, list):
            try:
                raw_results = self._throttled_get(
                    self.SEARCH_URL,
                    {
                        "q": query,
                        "format": "jsonv2",
                        "addressdetails": 1,
                        "limit": max(1, min(8, int(config.get("search_limit", 5)))),
                        "accept-language": str(config.get("language", "es")),
                    },
                )
            except requests.RequestException as exc:
                return ActionResult.failure(f"No pude consultar el mapa: {exc}", error="geocoding_error")
            search_cache[key] = raw_results
            self.cache_store.save(cache)

        results = []
        for raw in raw_results:
            try:
                results.append(self._format_result(raw))
            except Exception:
                continue

        self._ui("open_map")
        self._ui("map_show_results", results, query)

        if not results:
            return ActionResult.failure(f"No encontré '{query}' en el mapa.", error="location_not_found")

        first = results[0]
        self._current = dict(first)
        self.event_bus.publish("map.location_found", {"query": query, "result": first}, "navigation")
        return ActionResult.success(
            f"Localicé {first['name']} y abrí {len(results)} resultado(s).",
            query=query,
            location=first,
            results=results,
        )

    def fly_to(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("query") or params.get("place") or "").strip()
        if query and (params.get("lat") is None or params.get("lon") is None):
            return self.search({"query": query})

        try:
            lat = float(params["lat"])
            lon = float(params["lon"])
        except (KeyError, TypeError, ValueError):
            return ActionResult.failure("Necesito una ubicación o coordenadas válidas.", error="invalid_coordinates")

        height = float(params.get("height") or params.get("altitude") or 18_000)
        name = str(params.get("name") or params.get("label") or f"{lat:.5f}, {lon:.5f}")
        self._current = {"name": name, "lat": lat, "lon": lon, "height": height}
        self._ui("open_map")
        self._ui("map_fly_to", lat, lon, height, name)
        self.event_bus.publish("map.navigation_started", dict(self._current), "navigation")
        return ActionResult.success(f"Navegando hacia {name}.", location=dict(self._current))

    def global_view(self, _params: dict[str, Any] | None = None) -> ActionResult:
        config = self._config()
        default = dict(config.get("default_view") or {})
        self._current = default
        self._ui("open_map")
        self._ui("map_global_view")
        return ActionResult.success("Regresé a la vista global.", location=default)

    def home(self, _params: dict[str, Any] | None = None) -> ActionResult:
        home = dict(self._config().get("home") or {})
        if home.get("lat") is None or home.get("lon") is None:
            self.global_view({})
            return ActionResult.failure(
                "Todavía no has configurado una ubicación principal. Selecciona un punto y pulsa FIJAR CASA.",
                error="home_not_configured",
            )
        return self.fly_to(home)

    def set_home(self, params: dict[str, Any]) -> ActionResult:
        try:
            lat = float(params["lat"])
            lon = float(params["lon"])
        except (KeyError, TypeError, ValueError):
            return ActionResult.failure("Coordenadas inválidas para la ubicación principal.")
        config = self._config()
        config["home"] = {
            "name": str(params.get("name") or "Casa"),
            "lat": lat,
            "lon": lon,
            "height": float(params.get("height") or 18_000),
        }
        self.config_store.save(config)
        return ActionResult.success(f"Guardé {config['home']['name']} como ubicación principal.", home=config["home"])

    def save_location(self, params: dict[str, Any]) -> ActionResult:
        try:
            lat = float(params["lat"])
            lon = float(params["lon"])
        except (KeyError, TypeError, ValueError):
            return ActionResult.failure("Coordenadas inválidas.")
        name = str(params.get("name") or f"Ubicación {lat:.4f}, {lon:.4f}").strip()
        store = self.locations_store.load()
        locations = list(store.get("locations") or [])
        normalized = self._normalize(name)
        locations = [item for item in locations if self._normalize(item.get("name", "")) != normalized]
        item = {"name": name, "lat": lat, "lon": lon, "height": float(params.get("height") or 18_000)}
        locations.append(item)
        self.locations_store.save({"version": 1, "locations": locations})
        self._ui("map_add_marker", lat, lon, name)
        return ActionResult.success(f"Guardé la ubicación {name}.", location=item)

    def list_saved(self, _params: dict[str, Any] | None = None) -> ActionResult:
        locations = list(self.locations_store.load().get("locations") or [])
        return ActionResult.success(f"Hay {len(locations)} ubicaciones guardadas.", locations=locations)

    def reverse(self, params: dict[str, Any]) -> ActionResult:
        try:
            lat = float(params["lat"])
            lon = float(params["lon"])
        except (KeyError, TypeError, ValueError):
            return ActionResult.failure("Coordenadas inválidas.")

        cache = self.cache_store.load()
        reverse_cache = cache.setdefault("reverse", {})
        key = f"{lat:.5f},{lon:.5f}"
        raw = reverse_cache.get(key)
        if not isinstance(raw, dict):
            try:
                raw = self._throttled_get(
                    self.REVERSE_URL,
                    {
                        "lat": lat,
                        "lon": lon,
                        "format": "jsonv2",
                        "addressdetails": 1,
                        "accept-language": self._config().get("language", "es"),
                    },
                )
            except requests.RequestException as exc:
                return ActionResult.failure(f"No pude identificar el punto: {exc}")
            reverse_cache[key] = raw
            self.cache_store.save(cache)

        display = str(raw.get("display_name") or f"{lat:.5f}, {lon:.5f}")
        name = str(raw.get("name") or display.split(",", 1)[0])
        self._current = {"name": name, "display_name": display, "lat": lat, "lon": lon, "height": 18_000}
        self._ui("map_set_status", f"PUNTO IDENTIFICADO · {name}", "#39ff88")
        return ActionResult.success(f"El punto corresponde a {display}.", location=dict(self._current))

    def clear_markers(self, _params: dict[str, Any] | None = None) -> ActionResult:
        self._ui("map_clear_markers")
        return ActionResult.success("Limpié los marcadores del mapa.")

    def status(self, _params: dict[str, Any] | None = None) -> ActionResult:
        config = self._config()
        return ActionResult.success(
            "Sistema holográfico de navegación disponible.",
            current=dict(self._current),
            home=dict(config.get("home") or {}),
            saved=list(self.locations_store.load().get("locations") or []),
        )

    def shutdown(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
