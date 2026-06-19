# Arquitectura de Pavo's Robotic Projects Assistant

El proyecto fue escrito desde una carpeta vacía. No conserva `mark_core`, `nexus`, conexiones seriales en la UI ni controladores duplicados.

## Reglas

- `SerialService` es el único dueño de PySerial y de los hilos lectores.
- La UI solo edita configuración y pide acciones al `PrpController`.
- `CapabilityRegistry` es la única puerta de ejecución para voz, rutinas y botones.
- Las rutinas usan capacidades; no llaman directamente a Spotify, OBS o ESP32.
- Los secretos viven únicamente en `config/secrets.json`.
- El firmware recibe dispositivos por JSON y no contiene pines fijos.

## Flujo

UI / Gemini Live → PrpController → CapabilityRegistry → Services

RoutineEngine y ModeEngine usan el mismo registro de capacidades.
