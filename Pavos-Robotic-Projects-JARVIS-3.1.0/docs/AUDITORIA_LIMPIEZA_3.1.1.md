# Auditoría de limpieza PRP JARVIS 3.1.1

## Resultado

La limpieza se realizó sobre la versión estable 3.1.0 sin cambiar las funciones visibles.

- Archivos originales: 95
- Archivos finales antes del manifest: 85
- Tamaño original: 779,969 bytes
- Tamaño final antes del manifest: 750,718 bytes
- Pruebas originales: 8
- Pruebas finales: 10

No había archivos idénticos byte por byte. La duplicación importante era **funcional**: dos implementaciones distintas podían abrir el mismo puerto COM.

## Duplicación serial eliminada

Antes:

```text
main.py                         → conexión serial antigua
mark_core/adapters/esp32.py     → conexión serial configurable
```

Después:

```text
prp_core/adapters/esp32.py      → único propietario serial
```

La conexión se reutiliza para:

- conectar;
- comprobar salud;
- sincronizar GPIO;
- encender/apagar;
- alternar;
- consultar estado.

Una prueba simulada comprueba que toda la secuencia utiliza exactamente un solo handle serial.

## Archivos eliminados

- `config/domotics_devices.json`
- `config/esp32_serial.json`
- `memory/config_manager.py`
- `setup.py`
- `Iniciar_Jarvis_Sleep_Mode.bat`
- `docs/legacy/`
- `CHANGELOG_NEXUS.md`
- cachés Python y bytecode

## Elementos renombrados

- `mark_core/` → `prp_core/`
- `MarkPlatform` → `PRPPlatform`
- `tests/test_nexus_core.py` → `tests/test_prp_core.py`
- `docs/ARQUITECTURA_NEXUS.md` → `docs/ARQUITECTURA_PRP.md`

## Validaciones

- Todos los archivos Python compilan.
- Todos los JSON de configuración son válidos.
- Las 10 pruebas unitarias pasan.
- Solo un módulo importa PySerial.
- El protocolo ESP32 permanece en `jarvis-node-v1`.
- Los alias y nombres dinámicos siguen funcionando.
- Las rutinas, modos y automatizaciones conservan sus esquemas.
- El migrador no copia código antiguo.

## Archivos conservados deliberadamente

No se eliminaron acciones, agentes o adaptadores que parecen poco usados, porque están registrados dinámicamente o se invocan mediante herramientas de Gemini. La auditoría de imports no encontró módulos Python huérfanos, salvo el firmware, que se ejecuta en la ESP32 y no en la PC.
