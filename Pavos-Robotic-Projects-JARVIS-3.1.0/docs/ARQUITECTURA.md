# Arquitectura 2.0

UI → Controller → CapabilityRegistry → Services

La UI nunca importa `serial`, `sounddevice`, `spotipy`, `obsws_python` ni `google.genai`.
Cada recurso físico tiene un único dueño. El audio se selecciona, prueba y reinicia desde la interfaz.
