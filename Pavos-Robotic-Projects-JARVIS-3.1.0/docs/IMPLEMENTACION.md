# Implementación incluida

## Núcleo
- Registro único de capacidades.
- Bus de eventos.
- Motor de rutinas secuenciales, paralelas, opcionales, reintentos y rollback.
- Motor de modos persistentes.
- Motor de automatizaciones basado en eventos.

## Servicios
- Gemini Live con voz bidireccional.
- Audio adaptativo con preroll y sensibilidad configurable.
- Spotify Web API con búsqueda, alias, volumen, pausa y estado.
- OBS WebSocket con estado, escenas y grabación.
- ESP32 por un único SerialService.
- Estado de PC.
- Tareas locales.
- Gmail opcional por OAuth.
- Notificaciones locales.

## Interfaz
- Asistente.
- Nodos ESP32.
- Dispositivos y GPIO.
- Rutinas.
- Integraciones.
- Sensibilidad de audio.
- Alias multimedia.
- Tareas.
- Registro de actividad.

## Límites de esta entrega
- El editor visual de rutinas permite ejecutar y revisar las definiciones; la edición avanzada se realiza en `config/routines.json`.
- La lectura del historial completo de notificaciones de Windows no se incluye todavía; sí existen notificaciones internas y locales.
- Gmail requiere un archivo OAuth de Google configurado por el usuario.
- La prueba física final de audio, OBS, Spotify y ESP32 debe realizarse en Windows con el hardware real.
