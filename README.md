Receptor-anlizador CAN prototipo de prueba para prueba deepsea


El programa recibe tramas CAN BUS simple desde la interfaz VCAN0 o CAN0.
Cuando las tramas llegan estas se separan segunn la informaciòn que llega.

1. Telemetria.
2. Diagnostico.
3. Fallas.

Con los indicadores:

0x100 - 0x103   → Telemetría
0x1F0           → Fallas
0x6F0 - 0x6F3   → Diagnóstico fragmentado

Segun el CAIN id se procesan en contextos diferentes
