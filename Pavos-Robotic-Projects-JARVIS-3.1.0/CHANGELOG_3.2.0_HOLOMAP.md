# PRP JARVIS 3.2.0 — HOLOMAP

## Interfaz

- Nuevo selector de vista `NÚCLEO / HOLOMAP / CONTROL`.
- El mapa ocupa el viewport completo y devuelve los paneles al regresar al núcleo.
- Transición de entrada por opacidad.
- Estados visuales consolidados:
  - standby azul muy claro;
  - analizando verde neón;
  - navegación azul eléctrico.
- El HUD central y sus animaciones existentes permanecen intactos.

## Navegación holográfica

- Globo 3D CesiumJS integrado mediante Qt WebEngine.
- Búsqueda con Nominatim y caché local.
- Vuelos cinematográficos a ciudades, monumentos, países y coordenadas.
- Marcadores, vista global, órbita automática y estilos holo/calles.
- Selección de puntos y geocodificación inversa.
- Ubicación principal y lugares guardados.
- Nueva pestaña MAPA en el Centro de Control.

## Voz y herramientas

- Nueva herramienta Gemini `map_navigation`.
- Nuevo comando local `/map [lugar]`.
- Once capacidades de navegación registradas en PRPPlatform.

## Compatibilidad

- Audio, Gemini, Spotify, OBS, ESP32, rutinas, modos y automatizaciones no fueron reescritos.
- El adaptador ESP32 sigue siendo el único propietario del puerto serial.
- Si Qt WebEngine falta, el resto de JARVIS inicia normalmente con un panel de diagnóstico del mapa.
