# Corrección de UnicodeDecodeError en Windows

Esta versión protege toda lectura de procesos externos en modo texto.

## Problema corregido

Windows puede devolver texto desde PowerShell, `tasklist`, `nvidia-smi`,
`schtasks`, FFmpeg y otras herramientas usando CP1252 u otra página de códigos,
mientras Python está configurado para UTF-8. Eso causaba excepciones como:

```text
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa1
```

## Solución incluida

- `sitecustomize.py` instala el parche desde el arranque de Python.
- `core/subprocess_compat.py` aplica `mbcs` y `errors="replace"` solamente a
  procesos abiertos en modo texto sin codificación explícita.
- Las lecturas binarias permanecen intactas.
- Los monitores permanentes de GPU y temperatura también tienen protección
  explícita.
- `INICIAR_JARVIS.bat` define la codificación segura para procesos de Windows.

El aviso de Qt relacionado con `SetProcessDpiAwarenessContext` puede seguir
apareciendo. Es una advertencia de escalado visual y no provoca este error.
