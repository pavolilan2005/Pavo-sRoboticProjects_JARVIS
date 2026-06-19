# Pavo's Robotic Projects // JARVIS 3.2.0 HOLOMAP

Evolución visual y geoespacial construida sobre la rama limpia y estable 3.1.1. Conserva voz, audio, Spotify, OBS, rutinas, memoria y domótica, e incorpora una interfaz multipágina y un globo 3D controlable mediante voz.

## Inicio rápido

1. Instala Python 3.11 o 3.12 desde python.org.
2. Ejecuta `INSTALAR_JARVIS.bat`.
3. Ejecuta `INICIAR_JARVIS.bat`.
4. Configura Gemini, Spotify y OBS en **CENTRO DE CONTROL PRP**.
5. Ejecuta `DIAGNOSTICO_JARVIS.bat` para validar la instalación.

## Arquitectura

```text
Voz / UI / Eventos
        │
        ▼
Gemini Live + comandos locales
        │
        ▼
PRPPlatform
        │
        ├── registro de capacidades
        ├── rutinas
        ├── modos
        ├── automatizaciones
        └── bus de eventos
        │
        ├── PC / aplicaciones
        ├── Spotify / multimedia
        ├── OBS
        ├── Gmail / notificaciones
        ├── ESP32 / domótica
        └── HOLOMAP / navegación 3D
```

Componentes principales:

- `main.py`: sesión Gemini Live, audio y enlace entre la UI y el núcleo.
- `ui.py`: interfaz futurista principal.
- `control_center_ui.py`: configuración visual.
- `map_ui.py`: interfaz del globo y controles holográficos.
- `prp_core/adapters/navigation.py`: geocodificación, caché y lugares guardados.
- `assets/map/cesium_prp.html`: escena CesiumJS del globo 3D.
- `prp_core/`: capacidades, rutinas, modos, automatizaciones y adaptadores.
- `prp_core/adapters/esp32.py`: **único propietario de los puertos seriales**.
- `config/`: configuración persistente, separada del código.
- `firmware/esp32_node/main.py`: firmware MicroPython configurable.

Consulta `docs/ARQUITECTURA_PRP.md` para más detalles.

## PRP Holographic Navigation

Pulsa **HOLOMAP** en la ventana principal o usa:

```text
/map
/map Pirámides de Giza
```

El módulo permite buscar lugares, volar a coordenadas, guardar puntos, fijar una ubicación principal, activar órbita automática y alternar entre estilo holográfico y calles. También responde a frases como:

```text
Jarvis, abre el mapa.
Jarvis, llévame al CERN.
Jarvis, regresa a la vista global.
```

Consulta `docs/HOLOMAP.md`.

## Domótica ESP32

El proyecto utiliza exclusivamente el protocolo `jarvis-node-v1`.
Los nombres, alias, GPIO, tipo y estado activo se almacenan en:

- `config/nodes.json`
- `config/devices.json`
- `config/scenes.json`

Para modificar un dispositivo:

1. Abre **CENTRO DE CONTROL PRP → DISPOSITIVOS**.
2. Cambia nombre, alias, GPIO o tipo.
3. Pulsa **GUARDAR + SINCRONIZAR**.

La UI no abre puertos COM. Todas las operaciones pasan por `ESP32Adapter`, evitando conexiones duplicadas y errores de acceso al puerto.

## Audio

La configuración se guarda en `config/audio.json` y puede modificarse desde el menú **AUDIO**:

- micrófono y salida seleccionados;
- sensibilidad;
- ganancia;
- VAD adaptativo;
- calibración;
- preroll y cola de voz.

El flujo de audio abierto pertenece al runtime de Gemini. El adaptador de audio solo administra configuración y descubrimiento de dispositivos.

## Rutinas y modos

Las rutinas se guardan en `config/routines.json` y admiten:

- pasos secuenciales;
- bloques paralelos;
- esperas;
- condiciones;
- reintentos;
- pasos opcionales o críticos;
- rollback.

Los modos persistentes se encuentran en `config/modes.json` y las automatizaciones en `config/automations.json`.

## Integraciones

### Spotify

Configura `client_id`, `client_secret` y callback en **INTEGRACIONES**. El token OAuth se guarda localmente.

### OBS

Activa OBS WebSocket, define una contraseña y configura host, puerto y contraseña en **INTEGRACIONES**.

### Gmail

Guarda las credenciales OAuth de escritorio en `config/gmail_credentials.json`. El token se almacena localmente en `config/gmail_token.json`.

## Comandos locales útiles

```text
/control
/status
/ports
/esp32 COM5
/home foco on
/routines
/routine modo_stream
/mode start stream
/media play
/obs status
/pc
/mail
/notifications
/map Pirámides de Giza
/audio
/mic calibrate
```

## Migración

`MIGRAR_DESDE_ANTERIOR.bat` copia únicamente datos compatibles: claves, memoria, audio, integraciones, nodos, dispositivos, escenas, rutinas, modos, automatizaciones y configuración del mapa. No copia archivos Python antiguos.

## Pruebas

```text
DIAGNOSTICO_JARVIS.bat
python -m unittest discover -s tests -v
```

Los registros se guardan en `logs/jarvis.log`.

## Seguridad

No compartas:

- `config/api_keys.json`
- `config/gmail_credentials.json`
- `config/gmail_token.json`
- tokens OAuth o secretos de Spotify/OBS.

## Versión

- Base funcional: 3.1.0
- Limpieza estructural: 3.1.1
- Interfaz y navegación holográfica: 3.2.0
- Cambios detallados: `CHANGELOG_3.2.0_HOLOMAP.md`
