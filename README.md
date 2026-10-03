Receptor-anlizador CAN prototipo de prueba para prueba deepsea


El programa recibe tramas CAN BUS simple desde la interfaz VCAN0 o CAN0.
Cuando las tramas llegan estas se separan segunn la informaciòn que llega.

1. Telemetria.
2. Diagnostico.
3. Fallas.

Con los indicadores:

0x100 - 0x103   → Telemetría, se procesa con decode_telemetry(can_id,data)
0x1F0           → Fallas, se utiliza con decode_fault(data)
0x6F0 - 0x6F3   → Diagnóstico fragmentado
0x200 - 0x2FF Para ruido

Segun el CAIN id se procesan en contextos diferentes, esta pare 
es importante porque la informacion llega mezclada y debe ir alamacenando
en espacios de memoria diferentes lo que corresponde a cada ID.De esta forma
recuerda cada inforaciòn mientras van llegando las tramas completas.
despues de 150ms un contexto se cierra ya que se asume que no llegara 
el resto de la trama.
Tambien se resalta el diseño de un socket no bloquante, esto siginifica
 que si no llega ninguna trama, el hilo principal se queda alli detenido con el selector, entonces si hay datos devueve 
la trama sino lanza un Blocking IOError, y continua.
Para esto se usa un selector que espera eventos con un timeout, 
de esta forma si hay datos en el socket,procesa la informacion , pero si no hay datos en el socket espera un tiempo  continua la siguiente iteracion

