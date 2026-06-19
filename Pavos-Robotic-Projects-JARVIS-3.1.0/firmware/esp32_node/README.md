# Firmware genérico ESP32 para Pavo's Robotic Projects // JARVIS

1. Instala MicroPython en la ESP32.
2. Copia `main.py` a la raíz de la placa.
3. Reinicia la ESP32.
4. En **Centro de Control → Nodos**, cambia el protocolo a `jarvis-node-v1`, elige el puerto COM y guarda.
5. Crea o modifica dispositivos desde la pestaña **Dispositivos**.
6. Pulsa **Sincronizar nodo**. La configuración queda guardada en `jarvis_node_config.json` dentro de la placa.

Después de instalar este firmware puedes cambiar nombres, alias, pines, tipo, lógica activa y funciones sin volver a editar MicroPython.

Tipos incluidos:

- `digital_output`: relés, focos, actuadores simples.
- `digital_input`: botones, sensores de puerta y movimiento.
- `pwm_output`: brillo o velocidad de 0 a 100 %.
- `analog_input`: lectura ADC.

El protocolo usa una línea JSON por mensaje a través del USB serial.


## Ejemplo

Puedes asignar `Ventilador` al GPIO 2 desde el Centro de Control, guardar y sincronizar. Después acepta órdenes como `prende el ventilador`, `apaga el abanico` o `estado del fan`.
