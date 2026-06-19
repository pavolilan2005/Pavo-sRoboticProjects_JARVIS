# Arquitectura MARK XXXIX NEXUS

## Flujo principal

```text
Voz / UI / Eventos
        │
        ▼
Gemini Live o comandos locales
        │
        ▼
Planificador y registro de capacidades
        │
        ├── acciones individuales
        ├── rutinas
        ├── modos persistentes
        └── automatizaciones
        │
        ▼
Bus de eventos
        │
        ├── PC / Windows
        ├── OBS
        ├── Spotify / multimedia
        ├── Gmail / notificaciones
        └── ESP32 / escenas domóticas
```

## Capacidad

Una capacidad es una acción verificable con nombre estable, parámetros, riesgo, tiempo máximo y resultado estructurado. Ejemplos:

- `apps.open`
- `pc.status`
- `obs.set_scene`
- `spotify.play_track`
- `domotics.control`
- `email.unread`

## Rutina

Una rutina combina capacidades. Admite:

- pasos secuenciales;
- bloques paralelos;
- esperas;
- condiciones;
- reintentos;
- pasos críticos u opcionales;
- acciones de reversión;
- ejecución síncrona o en segundo plano;
- cancelación y seguimiento.

## Modo

Un modo ejecuta una rutina de entrada, permanece activo y puede vigilar condiciones. Al salir ejecuta una rutina de cierre. Los grupos exclusivos impiden activar simultáneamente, por ejemplo, Modo Stream y Modo Estudio.

## Automatización

Una automatización escucha eventos o intervalos y ejecuta capacidades, rutinas o modos. Incluye condiciones y cooldown para evitar ciclos.

## ESP32

La PC mantiene un registro lógico de nodos, dispositivos y escenas. El firmware genérico recibe una configuración JSON por serial y la guarda en la placa. JARVIS se refiere a IDs lógicos, no a GPIO fijos.

## Compatibilidad

El adaptador `legacy` permite usar el protocolo anterior mientras se migra gradualmente al protocolo `jarvis-node-v1`.
