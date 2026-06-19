# Cambios de optimización — Mark XXXIX

## Control por wake word

- Se añadió protocolo de activación por voz: para comandos hablados, Jarvis solo debe responder/actuar cuando escuche `Jarvis`.
- Los comandos escritos en la UI siguen funcionando aunque no escribas `Jarvis`; internamente se les antepone la palabra de activación.
- Se añadieron variaciones comunes de reconocimiento: `jarvis`, `jervis`, `yarvis`, `jarbis`, `charvis`.

> Nota: este cambio no añade un detector offline de wake word; Gemini sigue recibiendo audio para poder transcribir. Lo que sí cambia es que el asistente queda instruido y protegido para ignorar conversaciones de fondo. Para bloqueo local real, habría que agregar Porcupine/OpenWakeWord/Vosk.

## Interrupción / barge-in

- Antes el micrófono se apagaba mientras Jarvis hablaba; por eso no se podía interrumpir.
- Ahora el micrófono permanece activo durante la respuesta. Si detecta `Jarvis` mientras está hablando, vacía la cola de audio y permite que el nuevo comando tome prioridad.
- También se agregó interrupción manual desde la UI: botón `STOP SPEAKING` o tecla `ESC`.
- Para cortar sin nuevo comando puedes usar frases como `detente`, `cállate`, `silencio`, `stop`, `cancelar`, etc.

## Optimización ligera

- El monitor de métricas de la UI ahora refresca cada 5 s en lugar de cada 2 s.
- Se limpió el ZIP de `.git`, `__pycache__`, `.pyc`, API key real y memoria privada.
- Se corrigió `requirements.txt`: se quitó duplicado de Pillow y se agregaron dependencias usadas por el código.

## Archivos modificados

- `main.py`
- `ui.py`
- `core/prompt.txt`
- `requirements.txt`
- `.gitignore`

## Prueba rápida recomendada

1. Instala dependencias: `pip install -r requirements.txt`
2. Corre: `python main.py`
3. Prueba que no responda a conversación normal.
4. Di: `Jarvis, qué hora es` o `Jarvis, abre Chrome`.
5. Mientras hable, di: `Jarvis` + tu nuevo comando, o presiona `ESC`.
