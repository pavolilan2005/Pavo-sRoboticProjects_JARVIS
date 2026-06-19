# Arquitectura limpia

## Regla principal

Cada recurso físico o externo tiene un único propietario:

- `AudioService`: micrófono y salida de voz.
- `GeminiLiveService`: sesión Gemini Live y máquina de estados.
- `ESP32Adapter`: todos los puertos seriales y el mapa lógico de GPIO.
- `SpotifyAdapter`: cliente OAuth y reproducción.
- `OBSAdapter`: conexión WebSocket con OBS.
- `PRPPlatform`: registro central de capacidades.
- `MainWindow`: presentación y eventos de usuario; no abre hardware.

La UI únicamente emite intenciones. Nunca importa `serial`, `sounddevice`, Spotipy u OBS WebSocket.

## Estados de voz

```text
OFFLINE → CONNECTING → STANDBY
                         │ palabra Jarvis
                         ▼
                      LISTENING
                         ▼
                      THINKING
                         ▼
                      SPEAKING
                         ▼
                 ventana de seguimiento
                         ▼
                      STANDBY
```

## Domótica

Los comandos usan IDs lógicos, no GPIO directos:

```text
"prende la luz" → dispositivo "foco" → nodo "esp32_principal" → GPIO 23
```

El PC envía primero `configure`, la placa guarda `prp_node_config.json`, y después acepta `get`, `set` y `toggle`.

## Rutinas

El motor admite pasos secuenciales, bloques paralelos, esperas, reintentos, pasos críticos y rollback. Los modos persistentes utilizan rutinas de entrada y salida.
