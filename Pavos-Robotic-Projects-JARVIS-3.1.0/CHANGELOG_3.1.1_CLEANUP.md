# PRP JARVIS 3.1.1 — Limpieza estructural

## Objetivo

Limpiar la rama estable 3.1.0 sin alterar sus funciones visibles.

## Cambios internos

- Se renombró el núcleo interno `mark_core` a `prp_core`.
- `PRPPlatform` reemplaza el nombre interno anterior.
- Se eliminó la segunda implementación serial ubicada en `main.py`.
- `ESP32Adapter` es el único módulo que importa PySerial y abre puertos COM.
- Se eliminó el controlador de firmware serial de un carácter y su configuración duplicada.
- Se añadió `health_check()` reutilizando la conexión existente del nodo.
- La UI guarda el puerto seleccionado directamente en `nodes.json` mediante el adaptador.
- Se migró el puerto guardado anterior al nodo principal.
- Se actualizó el migrador para copiar únicamente datos compatibles.

## Archivos eliminados

- `config/domotics_devices.json`
- `config/esp32_serial.json`
- `memory/config_manager.py`
- `setup.py`
- `Iniciar_Jarvis_Sleep_Mode.bat`
- `docs/legacy/`
- `CHANGELOG_NEXUS.md`
- cachés `__pycache__` y bytecode

## Documentación

- README reescrito para la arquitectura actual.
- Arquitectura renombrada a `docs/ARQUITECTURA_PRP.md`.
- Eliminadas referencias visibles al proyecto anterior.
- Manifest SHA-256 regenerado.

## Compatibilidad

Se conservan:

- UI futurista;
- Gemini Live y wake word;
- memoria;
- audio configurable;
- Spotify;
- OBS;
- acciones de PC;
- tareas y agentes;
- rutinas, modos y automatizaciones;
- firmware `jarvis-node-v1`;
- nombres y alias dinámicos de dispositivos.
