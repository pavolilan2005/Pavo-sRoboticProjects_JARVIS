# Pavo's Robotic Projects // JARVIS 3.0.0

Reconstrucción limpia del asistente personal, basada en la experiencia visual y de uso del antiguo proyecto, pero sin reutilizar su arquitectura monolítica ni sus conexiones duplicadas.

## Qué corrige esta versión

- El estado **STANDBY** aparece en el HUD central y muestra `DI 'JARVIS' PARA ACTIVAR`.
- Durante la ventana de seguimiento se muestra una cuenta regresiva: `STANDBY EN Ns`.
- El micrófono se transmite de forma continua por defecto, por lo que no depende de superar un umbral RMS para escuchar la palabra de activación.
- El Centro de Control permite elegir micrófono, bocinas, ganancia y una compuerta de ruido opcional.
- La conexión serial existe en un único módulo: `prp/adapters/esp32.py`.
- Al conectar una ESP32, JARVIS sincroniza automáticamente los GPIO antes de controlar el foco.
- El firmware MicroPython recibe nombres, pines y funciones por JSON; no necesitas editarlo al cambiar un GPIO.
- Regresó la interfaz futurista tipo HUD con telemetría, reactor, actividad, audio y panel serial.
- Spotify, OBS, rutinas, modos, automatizaciones, tareas y domótica comparten el mismo registro de capacidades.
- El cerebro multimedia admite alias, playlists personales, canciones, artistas, álbumes y contexto temporal.

## Instalación limpia

1. Extrae el ZIP en una carpeta nueva.
2. Ejecuta `INSTALAR.bat`.
3. Ejecuta `INICIAR.bat`.
4. En el primer inicio escribe tu API key de Gemini.
5. Abre el Centro de Control desde el botón **CONTROL CENTER**.

No mezcles archivos Python de versiones anteriores. Para recuperar credenciales y configuraciones compatibles, primero instala y luego ejecuta `MIGRAR_CONFIG.bat`.

## Primera prueba de audio

1. Abre **Centro de Control → Audio**.
2. Selecciona explícitamente tu micrófono y tus bocinas.
3. Deja la compuerta de ruido desactivada para la primera prueba.
4. Usa ganancia `1.35` como punto de partida.
5. Pulsa **Guardar y reiniciar audio**.
6. Comprueba que el HUD reaccione cuando hablas.
7. Usa **Grabar y escuchar 4 s**.
8. Di con voz normal: `Jarvis, ¿me escuchas?`.

Cuando JARVIS termina de responder, permanece activo 30 segundos por defecto. El HUD muestra la cuenta regresiva y después regresa a **STANDBY**.

## Primera prueba de ESP32

1. Copia `firmware/esp32_node/main.py` a la raíz de la ESP32 con el nombre `main.py`.
2. Reinicia la placa y confirma el evento de arranque `prp-node-v1`.
3. Cierra Thonny para liberar el puerto COM.
4. En el panel lateral de JARVIS selecciona el COM y pulsa **CONECTAR**.
5. Debe mostrar `ESP32: EN LÍNEA` y `GPIO sincronizados`.
6. Prueba por voz: `Jarvis, prende el foco`.
7. El dispositivo inicial se llama `foco` y usa GPIO 23. Puedes cambiarlo en **Centro de Control → Dispositivos**.

Si el relé funciona al revés, activa **Activo bajo** para el dispositivo y vuelve a sincronizar el nodo.

## Arquitectura

```text
UI / Voz / Rutinas / Automatizaciones
                  │
             PRPPlatform
                  │
        CapabilityRegistry + EventBus
        ┌─────────┼──────────┬─────────┐
      ESP32    Spotify      OBS       PC
        │
  único enlace serial
```

Consulta `docs/ARQUITECTURA.md`, `docs/AUDIO_Y_STANDBY.md` y `docs/ESP32.md`.
