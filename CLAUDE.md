# Integracion_Matriculas

Repositorio de la integración custom de Home Assistant "Matrículas" de Maxi:
registro de matrículas e identificación de las lecturas LPR de Frigate. Es la
**fuente de verdad** del código y la fuente desde la que HACS la instala.

Es **público** a propósito, porque HACS no lee repos privados (ver
`Integracion_Riego/CLAUDE.md`). Por eso:

- **Nunca** subir matrículas ni nombres reales: ni el `plates.json` de casa
  (está en `.gitignore`), ni en tests, ni en la documentación, ni en los
  mensajes de commit. Las pruebas usan datos inventados.
- Las comprobaciones con datos reales se hacen en el scratchpad de la sesión.

## Entorno

- Repo local: `~/Downloads/GitHub/Integracion_Matriculas`
- HA real por Samba: `/Volumes/config` (si no está montado:
  `osascript -e 'mount volume "smb://192.168.1.9/config"'`). Frigate está en
  `/Volumes/app_configs/ccab4aaf_frigate/`.
- Esta sesión **no tiene credenciales de GitHub**: `git add` y `git commit`
  sí, `git push` no. El push, y crear el repo en GitHub, lo hace el usuario
  desde GitHub Desktop.

## Estructura

```
custom_components/matriculas/
  coincidencia.py   tolerancia a errores de OCR; no importa nada de HA
  almacen.py        registro + detecciones en .storage, importación del legado
  detector.py       suscripción MQTT a Frigate, deduplicación por coche
  __init__.py       alta de la entrada y servicios
  websocket.py      canal matriculas/suscribir del panel
  frontend/matriculas-panel.js   el panel (JS sin dependencias)
  sensor.py, event.py, entity.py, config_flow.py
docs/DECISIONES.md  por qué es así; NO va en custom_components
tests/test_matriculas.py
```

## Antes de tocar nada, lee `docs/DECISIONES.md`

En particular:

- `coincidencia.py` es un porte fiel de `custom_templates/matriculas.jinja`.
  Si cambias la lógica, cambia también la macro mientras siga en uso, y
  vuelve a comparar las dos (§3).
- Una coincidencia **aproximada sí abre** la puerta. Es decisión de Maxi, no
  un fallo (§4).
- El `plates.json` antiguo **nunca se modifica** desde aquí.

## Flujo para editar

1. Editar en el repo, dentro de `custom_components/matriculas/`.
2. Pasar las pruebas (abajo).
3. Commit (yo puedo). Push lo hace el usuario.
4. Subir la `version` de `manifest.json` cuando esté listo para probar: HACS
   detecta la actualización por ese número.
5. El usuario actualiza desde HACS y reinicia HA.

No copiar directamente en `/Volumes/config/custom_components/matriculas` sin
editar antes en el repo.

## Pruebas

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.9.2 paho-mqtt
/tmp/hav/bin/python tests/test_matriculas.py
node tests/test_panel.mjs
```

Para ver el panel sin HA: `tests/panel_demo.html` con datos inventados (la
sesión de Claude la sirve con `preview_start` y un `.claude/launch.json` en
`~/Downloads/GitHub`, que queda fuera del repo).

Las de Python arrancan un HA real (sin mocks) en un directorio temporal en ~2 s. El script
termina con `os._exit` porque, en este Mac, HA 2026.9.2 con Python 3.14.7 da
un segfault al cerrarse con cualquier entrada cargada, aunque sea de una
integración oficial. No es de esta integración (§6 de DECISIONES, que además
explica dos trampas del arnés al intentar aislar fallos así).

Trampas de HA 2026.9 ya conocidas: importar `homeassistant` antes que
cualquier cosa que importe `voluptuous`; los esquemas de los flujos se
serializan con `to_field_list` de `probatio`.
