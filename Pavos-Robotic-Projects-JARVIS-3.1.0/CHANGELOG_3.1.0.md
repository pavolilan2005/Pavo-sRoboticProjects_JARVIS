# Pavo's Robotic Projects // JARVIS 3.1.0

Esta versión parte directamente de la base funcional de **PAVO'S ROBOTIC PROJECTS // JARVIS 3.0.0** y añade únicamente dos bloques principales, sin reemplazar el resto del sistema.

## Menú de audio

El Centro de Control incorpora una pestaña **AUDIO** con:

- selección explícita de micrófono;
- selección explícita de bocinas o audífonos;
- sensibilidad de 1 a 100;
- ganancia digital de entrada;
- filtro adaptativo de ruido configurable;
- umbral RMS mínimo;
- duración de calibración;
- cola de voz posterior;
- estado del micrófono, ruido, umbral y RMS actual;
- recalibración manual;
- aplicación automática mediante reinicio controlado de la sesión de audio.

La configuración se almacena en `config/audio.json`.

## Dispositivos domóticos libres

JARVIS ya no limita la herramienta de domótica a focos, lámparas o LED. Puede controlar cualquier dispositivo registrado, por ejemplo:

- ventiladores;
- bombas;
- motores;
- puertas;
- relés;
- actuadores;
- sensores;
- dispositivos con nombres personalizados.

Los nombres, alias, GPIO, tipo y funciones se modifican desde **Centro de Control → DISPOSITIVOS**.

Se añadieron:

- resolución por ID, nombre visible o alias;
- tolerancia a frases como `el ventilador del cuarto`;
- normalización de acentos y artículos;
- renombrado seguro de IDs sin duplicar dispositivos;
- actualización de referencias de escenas al renombrar;
- listado de dispositivos disponible para Gemini;
- catálogo domótico dinámico dentro del prompt de JARVIS;
- botón **GUARDAR + SINCRONIZAR**;
- ejemplo `Ventilador` en GPIO 2.

## Firmware ESP32 1.1.0

El firmware genérico incluido elimina la llamada incompatible a `sys.stdout.flush()` y conserva el protocolo JSON `jarvis-node-v1`.
