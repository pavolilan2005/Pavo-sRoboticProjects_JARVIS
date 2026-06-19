# Corrección 2.0.2 — ciclo de vida de audio y Gemini

## Error corregido

```text
RuntimeError: Event loop is closed
```

El micrófono seguía enviando bloques después de que el ciclo asíncrono de Gemini
había terminado. Esto ocurría especialmente cuando `gemini_api_key` todavía
estaba vacía: Gemini salía, pero PortAudio continuaba activo.

## Cambios

- Gemini permanece en estado `OFFLINE` sin cerrar su event loop cuando falta la clave.
- Al guardar la clave en **INTEGRACIONES**, intenta conectarse automáticamente.
- El callback de PortAudio nunca propaga excepciones a CFFI.
- `push_mic()` comprueba sesión, estado del servicio y loop antes de enviar.
- El micrófono se detiene antes de cerrar el event loop.
- El cierre de la ventana cancela Gemini y libera audio/serial en orden.
- Si el micrófono inicial falla, la UI permanece abierta para seleccionar otro.

## Aplicación rápida

Puedes instalar el proyecto completo o extraer el hotfix encima de la carpeta
2.0.1 y aceptar el reemplazo de archivos. Tus archivos dentro de `config/` no
se sobrescriben con el hotfix.
