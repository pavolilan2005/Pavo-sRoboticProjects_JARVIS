# MARK XXXIX NEXUS 3.0

MARK XXXIX NEXUS es una reconstrucción modular de JARVIS orientada a:

- domótica configurable con ESP32;
- rutinas complejas y modos persistentes;
- control de aplicaciones, multimedia, OBS y Spotify;
- estado y administración básica de la PC;
- correo, notificaciones y automatizaciones;
- integración con Gemini Live mediante voz y herramientas verificables.

## Inicio rápido

1. Instala Python 3.11 o 3.12 desde python.org.
2. Ejecuta `INSTALAR_JARVIS.bat`.
3. Ejecuta `INICIAR_JARVIS.bat`.
4. Introduce tu API key de Gemini cuando la interfaz la solicite.
5. Abre **CENTRO DE CONTROL NEXUS** para configurar rutinas, modos, ESP32 e integraciones.

Para revisar la instalación ejecuta `DIAGNOSTICO_JARVIS.bat`.

## Qué cambió

La lógica dejó de estar concentrada en un solo archivo. La nueva arquitectura usa:

- `mark_core/event_bus.py`: bus central de eventos.
- `mark_core/capabilities.py`: registro de capacidades ejecutables.
- `mark_core/routines.py`: secuencias, paralelismo, condiciones, esperas, reintentos y rollback.
- `mark_core/modes.py`: estados persistentes como Stream o Estudio.
- `mark_core/automations.py`: reglas CUANDO → SI → HACER.
- `mark_core/adapters/`: conectores para PC, multimedia, OBS, Spotify, Gmail, Windows y ESP32.
- `control_center_ui.py`: editor visual y centro de actividad.

## Rutinas incluidas

### Modo Stream

- abre OBS, Spotify y el panel de Twitch en paralelo;
- espera a que las aplicaciones estén disponibles;
- intenta seleccionar la escena `Starting Soon`;
- reproduce la playlist `Stream` y ajusta volumen;
- activa la escena domótica `stream`;
- consulta el estado de la PC.

Los pasos opcionales no cancelan toda la rutina si una integración aún no está configurada.

### Terminar Stream

- detiene grabación si está activa;
- pausa Spotify;
- restaura la escena domótica `normal`.

### Modo Estudio

- abre Visual Studio Code y Spotify;
- reproduce la playlist `Focus`;
- ajusta volumen;
- activa la escena domótica `estudio`.

Todas pueden modificarse visualmente desde el Centro de Control.

## ESP32 configurable

NEXUS incluye firmware genérico en:

`firmware/esp32_node/main.py`

Después de instalarlo en una ESP32 con MicroPython, la PC puede enviarle por serial:

- nombre lógico del dispositivo;
- GPIO;
- tipo de pin;
- estado activo alto/bajo;
- funciones permitidas;
- escenas y comandos.

La placa guarda la configuración localmente. Para cambiar un foco de GPIO 23 a GPIO 18 basta editarlo en **DISPOSITIVOS** y pulsar **Sincronizar configuración**; no es necesario modificar el firmware.

El modo `legacy` conserva compatibilidad con el foco y los comandos anteriores mientras haces la migración.

## Integraciones

### OBS

En OBS activa el servidor WebSocket, establece una contraseña y configura host, puerto y contraseña en **INTEGRACIONES**. Las acciones críticas como iniciar transmisión requieren confirmación.

### Spotify

Crea una aplicación en Spotify Developer, añade el callback mostrado por NEXUS y configura `client_id` y `client_secret`. El control directo de reproducción depende de una cuenta compatible con la API de reproducción.

### Gmail

Descarga un archivo OAuth de aplicación de escritorio y guárdalo como:

`config/gmail_credentials.json`

La primera conexión abrirá el navegador para autorizar acceso. El token local se guarda en `config/gmail_token.json`.

### Notificaciones de Windows

La emisión de avisos funciona con la instalación normal. Para experimentar con lectura del historial de notificaciones ejecuta:

`INSTALAR_NOTIFICACIONES_WINDOWS.bat`

Windows puede pedir permisos y algunas aplicaciones no exponen todas sus notificaciones.

## Comandos locales útiles

```text
/control
/status
/routines
/routine modo_stream
/mode start stream
/mode stop stream
/media play
/media next
/obs status
/pc
/mail unread
/notifications
/ports
/home foco on
```

También se pueden expresar naturalmente por voz, por ejemplo:

- “Jarvis, activa modo stream.”
- “Pon la playlist Focus y baja el volumen al veinte por ciento.”
- “¿Qué tan cargada está la computadora?”
- “Lee mis correos no leídos.”
- “Prende la luz del escritorio.”

## Seguridad

El ZIP no incluye tu API key ni credenciales OAuth. No compartas estos archivos:

- `config/api_keys.json`
- `config/gmail_credentials.json`
- `config/gmail_token.json`
- credenciales de Spotify u OBS.

Las capacidades sensibles tienen niveles de riesgo. Iniciar transmisión, eliminar información o realizar acciones críticas debe requerir confirmación explícita.

## Migración

Ejecuta `MIGRAR_DESDE_ANTERIOR.bat` para copiar de forma selectiva tu API key, memoria y configuración domótica heredada desde una instalación anterior.

## Pruebas

- `DIAGNOSTICO_JARVIS.bat`: dependencias, audio, configuración, codificación y pruebas del núcleo.
- `python -m unittest discover -s tests -v`: pruebas unitarias del motor NEXUS.

Los registros se guardan en `logs/jarvis.log`.

---

# Actualización 3.1.0 — Audio y dispositivos personalizados

Esta compilación mantiene la interfaz y el comportamiento de NEXUS 3.0.0, pero muestra la marca visible **Pavo's Robotic Projects // JARVIS**.

## Configurar audio

Abre:

`CENTRO DE CONTROL → AUDIO`

1. Selecciona tu micrófono real.
2. Selecciona tus bocinas o audífonos.
3. Deja inicialmente sensibilidad `82 %` y ganancia `1.20`.
4. Pulsa **GUARDAR Y APLICAR**.
5. Guarda silencio durante la calibración.

JARVIS reinicia automáticamente la sesión de audio para aplicar el cambio. No necesitas cerrar la interfaz.

Si el teclado activa demasiado el micrófono, reduce la sensibilidad poco a poco, por ejemplo de `82` a `72`. Si debes levantar demasiado la voz, aumenta la sensibilidad o la ganancia.

## Configurar cualquier dispositivo ESP32

Abre:

`CENTRO DE CONTROL → DISPOSITIVOS`

Ejemplo para un ventilador:

- ID: `ventilador`
- Nombre: `Ventilador`
- Alias: `abanico, fan, ventilador del cuarto`
- Nodo: `esp32_principal`
- GPIO: `2`
- Tipo: `digital_output`
- Activo bajo: según tu relé o transistor
- Funciones: `on, off, toggle, status`

Pulsa **GUARDAR + SINCRONIZAR**. Después acepta órdenes como:

- `Jarvis, prende el ventilador.`
- `Apaga el abanico.`
- `Cambia el estado del fan.`
- `¿El ventilador del cuarto está encendido?`

Para que la asignación de GPIO sea remota, el nodo debe usar el protocolo `jarvis-node-v1` y el firmware incluido en `firmware/esp32_node/main.py`.
