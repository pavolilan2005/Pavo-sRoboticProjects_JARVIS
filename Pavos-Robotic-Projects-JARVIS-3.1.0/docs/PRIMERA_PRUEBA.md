# Primera prueba de PRP JARVIS 3.1.1

1. Ejecuta `DIAGNOSTICO_JARVIS.bat`.
2. Inicia JARVIS y espera el estado `STANDBY`.
3. Comprueba el medidor de micrófono y di “Jarvis” con voz normal.
4. Abre **CENTRO DE CONTROL PRP**.
5. En AUDIO confirma el micrófono y salida seleccionados.
6. En NODOS ESP32 verifica puerto, baudrate y protocolo `jarvis-node-v1`.
7. Pulsa conectar y después **GUARDAR + SINCRONIZAR** en DISPOSITIVOS.
8. Prueba manualmente `ENCENDER`, `ESTADO`, `APAGAR` y `ALTERNAR`.
9. Ejecuta `/home foco on` y una orden equivalente por voz.
10. Prueba Spotify, OBS y una rutina sin cerrar JARVIS.
11. Desconecta y reconecta la ESP32 una vez.
12. Déjalo abierto al menos 30 minutos y revisa `logs/jarvis.log`.

No deberían aparecer conexiones COM duplicadas, `PermissionError`, `Event loop is closed`, `ExceptionGroup` ni tracebacks repetitivos.
