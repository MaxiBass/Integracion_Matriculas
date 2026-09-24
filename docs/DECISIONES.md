# Decisiones — Matrículas

Registro de por qué la integración es como es. Antes de "mejorar" algo que
parezca raro, busca aquí si ya se decidió.

Este repositorio es **público**: aquí no aparecen matrículas ni nombres
reales. Las comprobaciones con datos reales se hicieron fuera del repo.

## 1. Qué sustituye

El sistema anterior, en el HA de casa, eran unas 25 piezas repartidas en 7
sitios:

- `packages/videoportero/`: `plates.json`, `save_plate.py`,
  `update_plate.py`, `delete_plate.py`, 4 `shell_command` que los lanzan y el
  `command_line` `sensor.plates_content` que hace `cat` del JSON cada 30 s.
- `packages/videoportero/helpers.yaml`: `input_text.matricula_pendiente`,
  `nombre_propietario`, `editar_matricula`, `editar_nombre`,
  `input_boolean.editar_notify`, `nueva_matricula_notify`.
- `scripts.yaml`: `guardar_matricula_nueva`, `actualizar_matricula`,
  `eliminar_matricula`, `cargar_matricula_editar`, `cancelar_edicion`,
  `limpiar_nueva_matricula`.
- `custom_templates/matriculas.jinja`: la macro `buscar_matricula`.
- Automatizaciones: "VTO - Visita unificada" (la parte de matrícula),
  "VTO - Guardar nombre desde notificación" y "VTO - Ignorar matrícula desde
  notificación".
- Dashboard `gestion_de_matriculas`.

Fallos que tenía y que esta integración corrige:

- **Pérdida total de datos.** `save_plate.py` y `update_plate.py` capturaban
  cualquier error al leer el JSON con un `except:` y seguían con un registro
  vacío, así que un fichero ilegible acababa sobrescrito con una sola
  matrícula. Además la escritura no era atómica.
- **Renombrar duplicaba.** Cambiar la matrícula en el formulario de edición
  creaba la nueva y dejaba la antigua.
- **Errores invisibles.** Un `shell_command` que falla no detiene el script;
  el formulario se vaciaba igual y parecía guardado.
- **Paso 3b de la macro muerto** (ver §3).
- **"Ignorar" no recordaba nada**: la misma desconocida volvía a preguntar.

## 2. Integración y no add-on

Un add-on es un contenedor aparte. Solo compensaría si hiciera el OCR, y eso
ya lo hace Frigate 0.18 (unos 55 ms por lectura en este equipo). Todo lo
demás —guardar datos, servicios, eventos, MQTT, entidades, un panel— lo da HA
por dentro, sin otro proceso que mantener ni una API por medio.

## 3. La tolerancia a errores es un porte fiel de la macro

`coincidencia.py` reproduce `buscar_matricula` paso a paso, incluida la
normalización posicional y el diccionario de confusiones, para que el cambio
de sistema no cambie qué coche se reconoce.

Verificado el 24/09/2026: la macro (ejecutada con el motor de plantillas de
HA 2026.9.2) y el porte dan **el mismo resultado en 949 casos**: las 50
lecturas distintas que Frigate había guardado en dos meses, más todas las
variantes de un carácter de 12 matrículas registradas y casos límite.

Con una diferencia a propósito: **el paso 3b funciona**. En la macro, la
lista de candidatos de "un carácter distinto cualquiera" se reasignaba dentro
de un `for` sin `namespace`; en Jinja esa asignación no sobrevive al bucle,
así que el paso nunca encontraba nada. En dos meses dejó sin reconocer dos
coches registrados, que abrieron una visita completa como desconocidos. La
macro de producción se corrigió el mismo día, y la comparación de arriba se
hizo contra la versión corregida.

Detalles que parecen mejorables y no se tocan:

- Con **más de un candidato** no se elige ninguno, y si 3a es ambiguo no se
  prueba 3b. Una lectura ambigua no es fiable.
- La normalización posicional (paso 1) no hace nada con la configuración
  actual de Frigate: su `format` (`^[0-9]{4}[BCDFGHJKLMNPRSTVWXYZ]{3}$`)
  descarta cualquier lectura con letras en la parte numérica o cifras en la
  de letras. Se mantiene por fidelidad y por si ese `format` cambia.

## 4. Una coincidencia aproximada SÍ abre la puerta

Decisión expresa de Maxi (24/09/2026). `abrir` del evento es el de la
matrícula registrada, se haya reconocido exacta o aproximada. No es un
descuido: no "arreglarlo".

Lo que sí no abre nunca: desconocidas, ignoradas y caducadas.

Las matrículas importadas del sistema anterior entran con `abrir: true`,
porque allí cualquier conocida con aviso abría cuando la apertura automática
estaba activa. Las nuevas también, por la misma razón. El control global
sigue siendo `input_boolean.apertura_automatica_al_timbrar`.

## 5. Almacenamiento en dos ficheros

- `.storage/matriculas.registro`: matrículas e ignoradas. Solo se escribe
  cuando alguien edita, siempre con `atomic_writes`.
- `.storage/matriculas.detecciones`: estadísticas e historial (500
  entradas). Cambia a menudo, así que se escribe con 60 s de retardo, y se
  vuelca al descargar la integración.

Separados para que las escrituras frecuentes nunca puedan tocar el registro.
Si HA encuentra uno corrupto, lo aparta como `.corrupt.<fecha>` y abre un
aviso en Reparaciones: no se pierde nada en silencio. Si el que falta es el
registro y existe el `plates.json` antiguo, se reimporta.

La importación automática solo ocurre cuando el registro no existe. Si falla
(fichero ilegible), no se guarda nada y se vuelve a intentar en el siguiente
arranque.

## 6. Pendiente: segfault al cerrar el intérprete en las pruebas

Con el Python 3.14.7 del venv de pruebas, cuando la entrada se ha cargado y
el detector ha arrancado, el intérprete da un segfault en la recogida de
basura mientras descarga los módulos, después de que todas las pruebas hayan
terminado. Se aisló hasta la tarea de fondo de `Detector.async_iniciar`, pero
la misma lógica copiada en otro módulo no lo reproduce, y descargar la
entrada antes de parar tampoco lo evita. No se encontró la causa.

`tests/test_matriculas.py` termina con `os._exit()` para que el código de
salida refleje las pruebas y no ese fallo.

**Verificar en producción**: tras instalar, reiniciar HA desde la interfaz y
comprobar en el registro del Supervisor que el núcleo se para limpio (sin
código 139).

## 7. Cada coche, un evento y una estadística

Frigate publica varias lecturas del mismo coche (mismo `id`) con
puntuaciones crecientes. El detector lanza `matriculas_detectada` la primera
vez y solo repite si la identificación mejora: de desconocida o ignorada a
caducada o conocida, o del mismo rango con más puntuación. Una lectura peor
no se anuncia.

Tras 30 s sin lecturas nuevas el coche se cierra y se anota **una vez** en
las estadísticas, con la mejor identificación. Así las lecturas malas previas
no inflan la lista de desconocidas.

## 8. `entity_id` fijos

`sensor.matriculas_registradas` y `event.matriculas_deteccion` se fijan en
el código. En HA 2026.9 el `entity_id` se genera a partir del nombre en
inglés salvo en algunos idiomas, y las automatizaciones necesitan un nombre
estable.

## 9. Plan de migración

1. **Fase 1 — en sombra** (esta versión). La integración importa el
   `plates.json`, escucha Frigate, lanza eventos y lleva estadísticas, pero
   nadie la usa todavía. El sistema anterior sigue mandando. Lo que se edite
   en el dashboard antiguo no llega a la integración: antes de la fase 3,
   ejecutar `matriculas.importar` (fusionando) para traerlo.
2. **Fase 2 — panel** en la barra lateral: tabla con búsqueda, edición,
   bandeja de desconocidas con la foto de Frigate.
3. **Fase 3 — cambio.** "VTO - Visita unificada" pasa a escuchar
   `matriculas_detectada` en vez del MQTT en bruto y la macro; las
   notificaciones de matrícula nueva llaman a `matriculas.guardar` e
   `matriculas.ignorar`. Después se retiran las piezas de §1.
