# Audio y standby

## Comportamiento predeterminado

La compuerta de ruido está desactivada. El micrófono transmite audio PCM de forma continua cuando JARVIS no está hablando. Esto evita cortar el comienzo de `Jarvis` y elimina la necesidad de gritar.

El ruido del teclado puede aparecer en la transcripción de entrada, pero no autoriza una respuesta cuando el sistema está en standby. Solo una transcripción que contenga una palabra de activación abre la ventana activa.

## Ajustes

- **Ganancia**: amplificación digital. Comienza con 1.35.
- **Sensibilidad**: solo afecta a la compuerta adaptativa.
- **Compuerta adaptativa**: reduce teclado/ventilador, pero conviene activarla únicamente después de comprobar el micrófono.
- **Micrófono/salida**: se guardan por índice de dispositivo.

## Standby

El valor predeterminado es 30 segundos después de una respuesta. Se modifica en `config/app.json` mediante `assistant.followup_seconds`.

El HUD muestra:

- `STANDBY · DI 'JARVIS' PARA ACTIVAR` cuando duerme.
- `VENTANA ACTIVA · STANDBY EN Ns` cuando acepta seguimientos.
