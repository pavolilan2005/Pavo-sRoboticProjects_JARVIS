# Firmware ESP32 — Pavo's Robotic Projects

1. Instala MicroPython en la ESP32.
2. Copia `main.py` a la raíz de la placa con ese nombre exacto.
3. Reinicia la ESP32. Debe aparecer un evento `boot` con protocolo `prp-node-v1`.
4. Cierra Thonny para liberar el puerto COM.
5. En JARVIS abre **Centro de Control → Nodos ESP32**, selecciona el COM y conecta.

La aplicación sincroniza automáticamente `config/devices.json` al conectarse. El foco inicial usa GPIO 23 y puede cambiarse desde la pestaña **Dispositivos** sin editar el firmware.
