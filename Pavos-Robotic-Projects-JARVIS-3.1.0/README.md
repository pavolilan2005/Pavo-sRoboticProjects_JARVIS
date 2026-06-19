# Pavo's Robotic Projects — JARVIS 2.0

Reconstrucción limpia centrada en estabilidad de audio y separación estricta de responsabilidades.

## Primer arranque
1. Ejecuta `INSTALAR.bat`.
2. Ejecuta `INICIAR.bat`.
3. Ve a **Integraciones** y guarda tu API key.
4. Ve a **Audio**, selecciona explícitamente tu micrófono y salida.
5. Pulsa **Guardar y reiniciar audio**.
6. Usa **Grabar y escuchar 4 segundos**. Si te escuchas, el hardware está bien.

## Por qué ahora no tienes que gritar
El micrófono se transmite continuamente a Gemini mientras JARVIS no habla. No se usa una compuerta RMS rígida por defecto. La sensibilidad queda disponible para futuras funciones, pero no bloquea tu voz.

## Arquitectura
- `AudioService`: único propietario de micrófono y bocinas.
- `SerialService`: único propietario de puertos COM.
- `GeminiLiveService`: única sesión Gemini.
- `Controller`: registro y ejecución de capacidades.
- `MainWindow`: solo UI; no abre serial ni streams.

## Seguridad
`config/secrets.json` queda excluido por `.gitignore`.

## Corrección 2.0.2

Esta versión corrige el cierre prematuro del event loop cuando Gemini todavía no
tiene API key y evita que el callback de PortAudio muestre `Python-CFFI error`.
La clave puede guardarse desde **INTEGRACIONES** y la conexión se reintenta sin
reiniciar la aplicación.
