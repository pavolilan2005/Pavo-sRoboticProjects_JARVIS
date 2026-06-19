# PRP Holographic Navigation System

## Qué incluye

- globo 3D integrado en la ventana principal;
- transición de cámara tipo vuelo;
- búsqueda de ciudades, monumentos, direcciones y países;
- marcadores pulsantes;
- selección directa sobre el planeta;
- geocodificación inversa de puntos;
- ubicación principal configurable;
- ubicaciones guardadas;
- vista global, órbita automática y modo visual holográfico/calles;
- control mediante interfaz, comandos escritos y voz.

## Abrir el mapa

Desde la interfaz pulsa `HOLOMAP`.

También puedes escribir:

```text
/map
/map Pirámides de Giza
/map CERN
```

Por voz:

```text
Jarvis, abre el mapa.
Jarvis, llévame a las pirámides de Giza.
Jarvis, muéstrame Tokio.
Jarvis, regresa a la vista global.
Jarvis, ve a casa.
```

## Configuración

`config/map.json` contiene idioma, vista inicial y ubicación principal.

`config/locations.json` contiene lugares guardados.

`config/map_cache.json` se crea automáticamente y evita repetir consultas de geocodificación.

## Dependencia visual

El mapa requiere `PyQt6-WebEngine`. El instalador lo instala desde `requirements.txt`. Si no está disponible, JARVIS conserva todas las demás funciones y muestra un panel de diagnóstico en lugar del globo.

## Conectividad

El globo carga CesiumJS desde su distribución oficial y utiliza mosaicos OpenStreetMap. La búsqueda usa Nominatim con caché local y limitación a una consulta por segundo. El módulo está diseñado para uso personal y de bajo volumen.

## Arquitectura

```text
Voz / UI / comando local
          │
          ▼
map_navigation
          │
          ▼
NavigationAdapter
   ├── geocodificación
   ├── caché
   ├── lugares guardados
   └── eventos
          │
          ▼
HolographicMapWidget
          │
          ▼
CesiumJS 3D globe
```

La UI renderiza; `NavigationAdapter` es el dueño de la búsqueda, configuración y persistencia.
