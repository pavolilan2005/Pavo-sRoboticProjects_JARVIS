# Arquitectura de Pavo's Robotic Projects // JARVIS

## Principio principal

Cada recurso físico o externo tiene un único propietario.

| Recurso | Propietario |
|---|---|
| Sesión Gemini Live | `JarvisLive` en `main.py` |
| Micrófono y bocinas abiertos | runtime de audio en `main.py` |
| Configuración de audio | `prp_core/adapters/audio.py` |
| Puertos COM y ESP32 | `prp_core/adapters/esp32.py` |
| Spotify | `prp_core/adapters/spotify.py` |
| OBS | `prp_core/adapters/obs.py` |
| Persistencia JSON | `prp_core/storage.py` |
| Presentación visual | `ui.py` y `control_center_ui.py` |

La UI expresa intenciones y muestra resultados; no abre conexiones por su cuenta.

## Flujo de una orden

```text
Voz o texto
   │
   ▼
Gemini Live / comando local
   │
   ▼
PRPPlatform.tool_call()
   │
   ▼
CapabilityRegistry
   │
   ▼
Adaptador correspondiente
   │
   ▼
ActionResult + evento + UI
```

## Capacidades

Una capacidad es una acción con nombre estable, parámetros y resultado estructurado. Ejemplos:

- `apps.open`
- `pc.status`
- `spotify.play_track`
- `obs.set_scene`
- `domotics.control`
- `esp32.sync`

## Rutinas

`RoutineEngine` combina capacidades y admite secuencias, paralelismo, condiciones, esperas, reintentos y rollback.

## Modos

`ModeManager` activa una rutina de entrada, mantiene estado persistente y puede ejecutar una rutina de salida.

## Automatizaciones

`AutomationEngine` escucha eventos y ejecuta capacidades, rutinas o modos con condiciones y cooldown.

## ESP32

Solo `ESP32Adapter` importa PySerial y crea objetos `serial.Serial`.

```text
UI / voz / rutina
       │
       ▼
PRPPlatform
       │
       ▼
ESP32Adapter
       │
       ▼
Una conexión por nodo
       │
       ▼
Firmware jarvis-node-v1
```

Los dispositivos son entidades lógicas. JARVIS controla `ventilador`, `foco` o cualquier alias; el adaptador resuelve el nodo y GPIO correspondiente.

## Configuración

```text
config/
├── api_keys.json
├── audio.json
├── integrations.json
├── nodes.json
├── devices.json
├── scenes.json
├── routines.json
├── modes.json
├── mode_state.json
└── automations.json
```

No se utilizan archivos de configuración serial o domótica duplicados.

## Navegación holográfica 3.2.0

```text
Gemini / comando local / UI
            │
            ▼
      map_navigation
            │
            ▼
 NavigationAdapter
   ├── Nominatim geocoding
   ├── cache JSON
   ├── home / saved locations
   └── EventBus
            │
            ▼
 HolographicMapWidget
            │
            ▼
 CesiumJS + Qt WebEngine
```

La UI no realiza peticiones de geocodificación. `NavigationAdapter` es el único propietario de la búsqueda, caché y persistencia de ubicaciones.
