# ESP32 y GPIO configurables

## Firmware

Instala MicroPython y copia `firmware/esp32_node/main.py` a la raíz de la placa.

Al arrancar emite:

```json
{"event":"boot","ok":true,"protocol":"prp-node-v1","firmware":"3.0.0","devices":0}
```

## Flujo de conexión

1. El PC abre el puerto a 115200 baud.
2. Envía `hello`.
3. Comprueba `prp-node-v1`.
4. Envía `configure` con todos los dispositivos de ese nodo.
5. La ESP32 guarda la configuración.
6. JARVIS manda `set`, `get` o `toggle` usando el ID lógico.

## Foco inicial

```text
ID: foco
Nodo: esp32_principal
GPIO: 23
Tipo: digital_output
Activo bajo: no
Alias: luz, lámpara, led
```

Para un módulo relé activo en bajo cambia **Activo bajo** a `sí` y pulsa **Sincronizar pines**.

Evita GPIO 6–11. Los GPIO 34, 35, 36 y 39 son únicamente de entrada en la ESP32 clásica.
