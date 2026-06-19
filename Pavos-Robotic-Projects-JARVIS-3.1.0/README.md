# Pavo's Robotic Projects Assistant

Asistente modular de voz, domótica y automatización de PC creado para **Pavo's Robotic Projects**.

## Instalación

1. Extrae el proyecto en una carpeta nueva.
2. Ejecuta `INSTALAR.bat`.
3. Abre `config/secrets.json` y coloca `gemini_api_key`.
4. Ejecuta `INICIAR.bat`.

## Sensibilidad de voz

La sensibilidad inicial es 78/100. El VAD usa ruido adaptativo, 550 ms de preroll y un umbral que disminuye al aumentar la sensibilidad. Ya no existe el límite rígido de 800 que obligaba a gritar. Ajusta el valor desde la pestaña **Audio** y reinicia.

## ESP32

Copia `firmware/esp32_node/main.py` a la placa como `main.py`. Agrega el nodo en `config/nodes.json`, por ejemplo:

```json
{"nodes":[{"id":"esp32_habitacion","name":"ESP32 Habitación","port":"COM6","baudrate":115200}]}
```

Después crea dispositivos desde la pestaña Domótica y sincroniza el nodo.

## Integraciones

Spotify y OBS se configuran en la pestaña Integraciones. La contraseña de OBS y secretos de Spotify se guardan en `config/secrets.json`.
