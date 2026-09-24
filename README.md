# Matrículas

Integración personalizada de Home Assistant que identifica las matrículas
que lee [Frigate](https://frigate.video) (LPR) contra un registro propio, y
permite gestionar ese registro con servicios.

- Escucha `frigate/tracked_object_update` y, por cada coche, lanza el evento
  `matriculas_detectada` ya resuelto: quién es, si hay que avisar y si puede
  abrir.
- Tolera errores de lectura del OCR (confusiones típicas y un carácter
  distinto) sin elegir nunca entre dos candidatos.
- Guarda el registro en `.storage/` con escritura atómica. Un fallo nunca
  borra las matrículas.
- Lleva estadísticas por matrícula (primera y última vez vista, veces) y un
  historial de las últimas 500 detecciones, también de las desconocidas.

## Instalar vía HACS

1. HACS → menú de los tres puntos → **Repositorios personalizados**.
2. URL: `https://github.com/MaxiBass/Integracion_Matriculas`, categoría
   **Integración**.
3. Instalar **Matrículas** y reiniciar Home Assistant.
4. Ajustes → Dispositivos y servicios → **Añadir integración** →
   **Matrículas**.
   - **Prefijo MQTT de Frigate**: el `topic_prefix` de Frigate (casi siempre
     `frigate`).
   - **Cámaras**: las cámaras de Frigate que cuentan. Vacío: todas.

Si existe `/config/packages/videoportero/plates.json` (el formato del
sistema anterior, `{"plates": {"1234BCD": {"name": …, "notify": …}}}`), se
importa automáticamente la primera vez. El fichero no se modifica.

MQTT es opcional: sin él no llegan lecturas, pero los servicios funcionan.

## Panel

La integración añade **Matrículas** a la barra lateral, para todos los
usuarios:

- **Registradas**: búsqueda por matrícula o nombre (sin importar tildes),
  orden por nombre, última visita o veces vista, y un diálogo para añadir,
  editar (también cambiar la matrícula), poner caducidad o eliminar.
- **Desconocidas**: las que ha leído Frigate y no están registradas, de más a
  menos vistas, con la foto de la última vez. Se añaden o se ignoran con un
  toque.
- **Historial**: las últimas 100 detecciones, con foto y la lectura original
  cuando se reconoció de forma aproximada.
- **Ignoradas**: para dejar de ignorarlas.

Se actualiza solo cuando algo cambia. Las fotos salen del proxy de
notificaciones de la integración de Frigate
(`/api/frigate/notifications/<id>/thumbnail.jpg`); si Frigate ya no conserva
una, no se muestra.

## Evento `matriculas_detectada`

| Campo | Significado |
|---|---|
| `tipo` | `conocida`, `desconocida`, `ignorada` o `caducada` |
| `conocida` | `true` solo si es `conocida` |
| `matricula` | La registrada con la que coincide; si no hay, la leída |
| `leida` | Lo que leyó Frigate |
| `aproximada` | `true` si se identificó con tolerancia a errores |
| `metodo` | `exacta`, `normalizada`, `confusion`, `un_caracter` o vacío |
| `candidatos` | Si la lectura era ambigua, las posibles |
| `nombre` | Nombre de la registrada (también en `caducada`) |
| `avisar` | Conocida: su ajuste. Desconocida y caducada: `true`. Ignorada: `false` |
| `abrir` | Conocida (también si es aproximada): su ajuste. El resto: `false` |
| `score`, `camara`, `frigate_id`, `hora` | Datos de la lectura |

Un mismo coche (mismo id de Frigate) solo repite el evento si una lectura
posterior lo identifica mejor: de desconocido a conocido, o con más
puntuación.

```yaml
triggers:
  - trigger: event
    event_type: matriculas_detectada
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.avisar }}"
actions:
  - action: notify.mobile_app_telefono
    data:
      message: >-
        {{ trigger.event.data.nombre or 'Coche desconocido' }}
        ({{ trigger.event.data.matricula }})
      data:
        image: /api/frigate/notifications/{{ trigger.event.data.frigate_id }}/snapshot.jpg
```

## Servicios

| Servicio | Qué hace |
|---|---|
| `matriculas.guardar` | Crea o sobrescribe una matrícula |
| `matriculas.editar` | Cambia solo los campos indicados; `nueva_matricula` la renombra |
| `matriculas.eliminar` | La borra del registro (conserva sus estadísticas) |
| `matriculas.ignorar` | No volver a avisar de una desconocida |
| `matriculas.dejar_de_ignorar` | Deshace lo anterior |
| `matriculas.buscar` | Identifica una lectura como si llegara de Frigate (solo respuesta) |
| `matriculas.listar` | Registradas con estadísticas, ignoradas y desconocidas más vistas (solo respuesta) |
| `matriculas.importar` | Importa un `plates.json` (fusionando o reemplazando) |

Cada matrícula tiene `nombre`, `avisar`, `abrir` (puede abrir), `notas` y
`caduca` (último día en que se reconoce). Los errores (matrícula inválida,
que no existe…) se muestran en pantalla.

## Entidades

- `sensor.matriculas_registradas`: número de matrículas, con las ignoradas y
  caducadas como atributos.
- `event.matriculas_deteccion`: cada detección, para el historial y el
  diario.

## Pruebas

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.9.2 paho-mqtt
/tmp/hav/bin/python tests/test_matriculas.py
node tests/test_panel.mjs
```

Las de Python arrancan un Home Assistant real en un directorio temporal; con
`python3` a secas solo se ejecutan las de coincidencia. Las de Node prueban la
lógica del panel.

`tests/panel_demo.html` muestra el panel con datos inventados y un `hass`
falso que se comporta como la integración: sirve la carpeta con un servidor
estático cualquiera y ábrela en el navegador (`?tema=oscuro`, `?vacio=1`).
