# JARVIS Mark XXXIX — versión corregida y optimizada

Esta entrega integra en un solo proyecto las correcciones de interfaz, audio,
micrófono, Gemini Live, ESP32 y estabilidad.

## Inicio recomendado

1. Ejecuta `INSTALAR_JARVIS.bat` una vez.
2. Revisa `config/api_keys.json`.
3. Ejecuta `INICIAR_JARVIS.bat`.
4. Si algo falla, ejecuta `DIAGNOSTICO_JARVIS.bat` y revisa `logs/jarvis.log`.

## Correcciones integradas

- Compatibilidad PyQt6 mediante `_RootShim.after()` y cola segura para la UI.
- Reproducción completa del audio sin eliminar fragmentos.
- Conversión de 24 kHz de Gemini a la frecuencia real del dispositivo de salida.
- VAD adaptativo con preroll para no cortar el inicio de “Jarvis”.
- Calibración resistente a golpes, notificaciones y voz durante el arranque.
- Envío Live mediante `audio=types.Blob(...)`.
- Lectura de PCM desde `model_turn.parts[].inline_data`.
- Errores de `TaskGroup` desglosados por nombre de tarea.
- Reanudación y compresión experimentales desactivadas por defecto.
- Reconexión progresiva y descarte de handles dañados.
- Comunicación serial y watchdog de ESP32 sin bloquear la interfaz.
- SDK antiguo `google.generativeai` eliminado del proyecto.
- Logs rotativos y comandos locales de diagnóstico.

## Comandos locales

```text
/help
/status
/audio
/mic
/mic calibrate
/mic devices
/ports
/esp32 COM6
/home foco on
/home foco off
/home foco toggle
/home foco status
/wake
/sleep
/stop
```

## Variables opcionales

```bat
set JARVIS_INPUT_DEVICE=nombre o índice del micrófono
set JARVIS_OUTPUT_DEVICE=nombre o índice de las bocinas
set JARVIS_OUTPUT_SAMPLE_RATE=48000
set JARVIS_MIC_MIN_RMS=16
set JARVIS_MIC_MAX_RMS=6000
set JARVIS_MIC_NOISE_MULTIPLIER=1.85
set JARVIS_ESP32_PORT=COM6
```

Las funciones experimentales permanecen apagadas. Solo para pruebas:

```bat
set JARVIS_SESSION_RESUMPTION=1
set JARVIS_CONTEXT_COMPRESSION=1
```

## Revisión 2026.06.15.2 — Codificación de procesos en Windows

Se corrigió globalmente el error `UnicodeDecodeError` producido cuando una
herramienta de Windows devolvía CP1252/OEM y Python intentaba leerla como UTF-8.
El parche se instala antes de cargar la interfaz y las acciones, conserva
intactos los procesos binarios y usa reemplazo seguro para caracteres inválidos.
El diagnóstico incluye ahora una prueba específica para este caso.
