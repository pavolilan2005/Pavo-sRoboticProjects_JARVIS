# Mark-XXXIX — Sleep Mode ajustado

Esta versión arranca en estado **SLEEPING** y despierta cuando detecta "Jarvis".

## Cambios de esta versión

- Ventana activa inicial: `AWAKE_WINDOW_SECONDS = 25.0`.
- Después de que Jarvis termina de hablar, queda despierto otros `POST_RESPONSE_AWAKE_SECONDS = 20.0` para que puedas contestarle sin repetir "Jarvis".
- La interrupción por voz sigue desactivada. Solo se puede cortar con **ESC** o el botón **STOP SPEAKING**.
- El umbral del micrófono bajó a `MIC_RMS_THRESHOLD = 230.0` para que no tengas que gritar.
- El rastro de voz subió a `MIC_SPEECH_TRAIL_SECONDS = 1.10` para no cortar palabras al final.

## Ajuste fino

En `main.py`, puedes modificar:

```python
AWAKE_WINDOW_SECONDS = 25.0
POST_RESPONSE_AWAKE_SECONDS = 20.0
MIC_RMS_THRESHOLD = 230.0
MIC_SPEECH_TRAIL_SECONDS = 1.10
```

Si Jarvis se despierta con ruido o conversaciones ajenas, sube `MIC_RMS_THRESHOLD` a 300-400.

Si Jarvis no te detecta bien, baja `MIC_RMS_THRESHOLD` a 150-220.

Si quieres tener más tiempo para contestar después de que habla, sube `POST_RESPONSE_AWAKE_SECONDS` a 30-45.
