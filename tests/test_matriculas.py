"""Pruebas de la integración Matrículas. Se ejecutan sin pytest:

    /tmp/hav/bin/python tests/test_matriculas.py

Las de coincidencia no necesitan Home Assistant. El resto arranca un Home
Assistant real (el del venv) en un directorio temporal, con la integración
enlazada en `custom_components/`, y la usa a través de sus servicios, igual
que una automatización. Si HA no está instalado, se saltan indicándolo.

Todas las matrículas y nombres son inventados: este repositorio es público.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

fallos: list[str] = []


def comprobar(condicion: bool, etiqueta: str) -> None:
    if condicion:
        print(f"  OK    {etiqueta}")
    else:
        print(f"  FALLO {etiqueta}")
        fallos.append(etiqueta)


# ── Coincidencia (Python puro) ───────────────────────────────────────


def test_coincidencia() -> None:
    # Se carga el fichero suelto, sin el paquete: así se prueba de paso que
    # no depende de Home Assistant.
    import importlib.util

    ruta = RAIZ / "custom_components" / "matriculas" / "coincidencia.py"
    spec = importlib.util.spec_from_file_location("coincidencia", ruta)
    co = importlib.util.module_from_spec(spec)
    sys.modules["coincidencia"] = co  # dataclass(slots=True) lo necesita
    spec.loader.exec_module(co)

    print("\nCoincidencia — porte de matriculas.jinja")

    conocidas = ["1234BCD", "5678FGH", "9012JKL", "3456BMX", "7777NBV"]

    def es(leida: str, esperada: str, metodo: str) -> None:
        r = co.buscar(leida, conocidas)
        comprobar(
            (r.matricula, r.metodo) == (esperada, metodo),
            f"{leida!r} → {esperada or '(ninguna)'} por {metodo or '-'}"
            f" (obtenido {r.matricula or '(ninguna)'} por {r.metodo or '-'})",
        )

    es("1234BCD", "1234BCD", co.EXACTA)
    es(" 1234-bcd ", "1234BCD", co.EXACTA)
    # Paso 1: una O en la parte numérica es un 0; un 8 en las letras, una B.
    es("I234BCD", "1234BCD", co.NORMALIZADA)
    es("12348CD", "1234BCD", co.NORMALIZADA)
    # Paso 3a: confusiones típicas del OCR.
    es("3456RMX", "3456BMX", co.CONFUSION)
    es("7777NBY", "7777NBV", co.CONFUSION)
    # Paso 3b: un carácter distinto cualquiera. En la macro Jinja este paso
    # no funcionaba (la lista de candidatos salía vacía del bucle).
    es("3456BVX", "3456BMX", co.UN_CARACTER)
    es("9012SKL", "9012JKL", co.UN_CARACTER)
    es("1234BCO", "1234BCD", co.UN_CARACTER)  # O↔D no está en las confusiones
    # Dos caracteres distintos: no es ninguna.
    es("9012SSL", "", "")
    es("", "", "")

    # Ambigüedad en 3a: dos candidatos igual de plausibles → ninguno, y 3b
    # no se prueba.
    amb = co.buscar("1111BCD", ["7111BCD", "1117BCD"])
    comprobar(not amb.encontrada and set(amb.candidatos) == {"7111BCD", "1117BCD"},
              "dos candidatos por confusión → ninguno, con los candidatos para diagnóstico")
    amb3b = co.buscar("1111BCD", ["1112BCD", "1111BCF"])
    comprobar(not amb3b.encontrada and len(amb3b.candidatos) == 2,
              "dos candidatos por un carácter → ninguno")
    comprobar(co.buscar("1234BC", conocidas).matricula == "", "longitud distinta nunca coincide")
    comprobar(co.es_formato_espanol("1234BCD") and not co.es_formato_espanol("1234ABC"),
              "formato español: sin vocales")


# ── Flujo de configuración y traducciones ────────────────────────────


def test_flujo_y_traducciones() -> None:
    import homeassistant  # noqa: F401  debe importarse antes que probatio/voluptuous
    import yaml
    from probatio import to_field_list

    from homeassistant.helpers import config_validation as cv

    from custom_components.matriculas import config_flow as cf

    print("\nFlujo de configuración y traducciones")

    try:
        campos = to_field_list(cf.esquema({}), custom_serializer=cv.custom_serializer)
        comprobar({c["name"] for c in campos} == {"prefijo_mqtt", "camaras"},
                  "el esquema del formulario se serializa")
    except Exception as err:  # noqa: BLE001
        comprobar(False, f"el esquema del formulario se serializa ({err!r})")

    limpio = cf.limpiar({"prefijo_mqtt": " /frigate/ ", "camaras": [" Videoportero-Sub ", "", "  "]})
    comprobar(limpio == {"prefijo_mqtt": "frigate", "camaras": ["Videoportero-Sub"]},
              f"limpia prefijo y cámaras vacías: {limpio}")
    comprobar(cf.limpiar({"prefijo_mqtt": "  "})["prefijo_mqtt"] == "frigate",
              "prefijo vacío → frigate")

    base = RAIZ / "custom_components" / "matriculas"
    es = json.loads((base / "translations" / "es.json").read_text("utf-8"))
    en = json.loads((base / "translations" / "en.json").read_text("utf-8"))
    cadenas = json.loads((base / "strings.json").read_text("utf-8"))

    def claves(d: dict, prefijo: str = "") -> set[str]:
        salida = set()
        for k, v in d.items():
            salida |= claves(v, f"{prefijo}{k}.") if isinstance(v, dict) else {f"{prefijo}{k}"}
        return salida

    comprobar(claves(es) == claves(en), "es.json y en.json tienen las mismas claves")
    comprobar(es == cadenas, "strings.json coincide con es.json")
    comprobar(es != en, "en.json no es una copia de es.json")

    servicios = yaml.safe_load((base / "services.yaml").read_text("utf-8"))
    sin_texto = [
        f"{s}.{c}"
        for s, datos in servicios.items()
        for c in (datos or {}).get("fields", {})
        if c not in es["services"].get(s, {}).get("fields", {})
    ]
    comprobar(set(servicios) == set(es["services"]) and not sin_texto,
              f"cada servicio y campo de services.yaml tiene traducción {sin_texto or ''}")

    import re
    codigo = "".join(p.read_text("utf-8") for p in base.glob("*.py"))
    usadas = set(re.findall(r'_error\(\s*"(\w+)"', codigo)) | set(
        re.findall(r'translation_key="(\w+)"', codigo)
    )
    faltan = usadas - set(es["exceptions"])
    comprobar(not faltan, f"todos los errores usados tienen mensaje {faltan or ''}")


# ── Home Assistant real ──────────────────────────────────────────────


LEGADO = {
    "plates": {
        "1234BCD": {"name": "Abuela", "notify": True},
        "5678FGH": {"name": "Reparto", "notify": False},
        "9012JKL": "Formato antiguo",  # el sistema anterior aceptaba el nombre a secas
        "3456BMX": {"name": "Fontanero", "notify": False},
        "12 34": {"name": "", "notify": True},  # entrada rota: se descarta
    }
}


async def _arrancar_hass(directorio: Path):
    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.core_config import async_process_ha_core_config
    from homeassistant.setup import async_setup_component

    hass = core.HomeAssistant(str(directorio))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    assert await bootstrap.async_load_base_functionality(hass)
    for dominio in bootstrap.CORE_INTEGRATIONS:
        assert await async_setup_component(hass, dominio, {}), dominio
    await async_process_ha_core_config(hass, {"time_zone": "Europe/Madrid"})
    hass.set_state(core.CoreState.running)
    return hass


async def _llamar(hass, servicio: str, datos: dict | None = None, respuesta: bool = False):
    return await hass.services.async_call(
        "matriculas", servicio, datos or {}, blocking=True, return_response=respuesta
    )


async def _falla(hass, servicio: str, datos: dict, clave: str) -> bool:
    from homeassistant.exceptions import ServiceValidationError

    try:
        await _llamar(hass, servicio, datos)
    except ServiceValidationError as err:
        return err.translation_key == clave
    return False


async def _recorrido(directorio: Path) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.matriculas import detector as mod_detector

    legado = directorio / "packages" / "videoportero" / "plates.json"
    legado.parent.mkdir(parents=True)
    legado.write_text(json.dumps(LEGADO), "utf-8")

    hass = await _arrancar_hass(directorio)
    try:
        # ── Alta ──
        r = await hass.config_entries.flow.async_init("matriculas", context={"source": "user"})
        comprobar(r["type"] == "form", "el flujo muestra el formulario")
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {"prefijo_mqtt": "frigate", "camaras": ["Videoportero-Sub"]}
        )
        comprobar(r["type"] == "create_entry", "el flujo crea la entrada")
        await hass.async_block_till_done()
        entrada = hass.config_entries.async_entries("matriculas")[0]
        comprobar(entrada.state is ConfigEntryState.LOADED, f"la entrada carga ({entrada.state})")

        r = await hass.config_entries.flow.async_init("matriculas", context={"source": "user"})
        comprobar(r["type"] == "abort", "no admite una segunda entrada")

        almacen = entrada.runtime_data.almacen
        detector = entrada.runtime_data.detector

        # ── Importación automática ──
        comprobar(set(almacen.matriculas) == {"1234BCD", "5678FGH", "9012JKL", "3456BMX"},
                  f"importa el plates.json al arrancar por primera vez ({sorted(almacen.matriculas)})")
        comprobar(almacen.matriculas["9012JKL"]["nombre"] == "Formato antiguo"
                  and almacen.matriculas["9012JKL"]["avisar"] is True,
                  "entiende el formato antiguo (nombre a secas)")
        comprobar(all(d["abrir"] for d in almacen.matriculas.values()),
                  "las importadas pueden abrir (como hasta ahora)")
        comprobar(json.loads(legado.read_text("utf-8")) == LEGADO, "el plates.json no se toca")
        comprobar((directorio / ".storage" / "matriculas.registro").exists(),
                  "el registro se escribe en .storage")

        estado = hass.states.get("sensor.matriculas_registradas")
        comprobar(estado is not None and estado.state == "4",
                  f"sensor.matriculas_registradas = 4 ({estado and estado.state})")

        # ── Guardar ──
        r = await _llamar(hass, "guardar", {"matricula": "7777-nbv", "nombre": "  Tío   Paco "}, True)
        comprobar(r["nueva"] and r["ficha"]["matricula"] == "7777NBV" and r["ficha"]["nombre"] == "Tío Paco",
                  "guardar normaliza matrícula y nombre")
        comprobar(r["ficha"]["avisar"] and r["ficha"]["abrir"], "una nueva avisa y puede abrir por defecto")
        await hass.async_block_till_done()
        comprobar(hass.states.get("sensor.matriculas_registradas").state == "5",
                  "el sensor se actualiza al guardar")
        comprobar(await _falla(hass, "guardar", {"matricula": "1", "nombre": "X"}, "matricula_invalida"),
                  "rechaza una matrícula de 1 carácter con error visible")
        comprobar(await _falla(hass, "guardar", {"matricula": "1111BBB", "nombre": "  "}, "nombre_vacio"),
                  "rechaza un nombre vacío con error visible")

        # ── Editar y renombrar ──
        r = await _llamar(hass, "editar", {"matricula": "7777NBV", "abrir": False}, True)
        comprobar(r["ficha"]["abrir"] is False and r["ficha"]["nombre"] == "Tío Paco",
                  "editar cambia solo lo indicado")
        r = await _llamar(hass, "editar", {"matricula": "7777NBV", "nueva_matricula": "7777NBW"}, True)
        comprobar("7777NBV" not in almacen.matriculas and r["ficha"]["matricula"] == "7777NBW"
                  and r["ficha"]["abrir"] is False,
                  "renombrar no deja la antigua duplicada y conserva los datos")
        comprobar(await _falla(hass, "editar", {"matricula": "7777NBW", "nueva_matricula": "1234BCD"}, "ya_existe"),
                  "no deja renombrar encima de otra existente")
        comprobar(await _falla(hass, "editar", {"matricula": "0000XXX", "nombre": "X"}, "no_existe"),
                  "editar una inexistente da error visible")
        await _llamar(hass, "editar", {"matricula": "7777NBW", "caduca": "2020-01-01"})
        comprobar(almacen.matriculas["7777NBW"]["caduca"] == "2020-01-01", "acepta caducidad")

        # ── Buscar ──
        r = await _llamar(hass, "buscar", {"matricula": "3456RMX"}, True)
        comprobar(r["tipo"] == "conocida" and r["matricula"] == "3456BMX" and r["aproximada"],
                  "buscar identifica una lectura aproximada")
        comprobar(r["abrir"] is True, "una coincidencia aproximada SÍ puede abrir (decisión de Maxi)")
        r = await _llamar(hass, "buscar", {"matricula": "7777NBW"}, True)
        comprobar(r["tipo"] == "caducada" and r["abrir"] is False and r["avisar"] is True,
                  "una caducada avisa pero no abre")
        r = await _llamar(hass, "buscar", {"matricula": "2222CCC"}, True)
        comprobar(r["tipo"] == "desconocida" and r["avisar"] and not r["abrir"],
                  "una desconocida avisa y no abre")

        # ── Ignorar ──
        await _llamar(hass, "ignorar", {"matricula": "2222CCC"})
        r = await _llamar(hass, "buscar", {"matricula": "2222CCC"}, True)
        comprobar(r["tipo"] == "ignorada" and r["avisar"] is False, "una ignorada ya no avisa")
        comprobar(await _falla(hass, "ignorar", {"matricula": "1234BCD"}, "ignorar_registrada"),
                  "no deja ignorar una registrada")
        await _llamar(hass, "guardar", {"matricula": "2222CCC", "nombre": "Ya conocido"})
        comprobar("2222CCC" not in almacen.ignoradas, "registrar una ignorada la saca de ignoradas")
        await _llamar(hass, "eliminar", {"matricula": "2222CCC"})
        comprobar(await _falla(hass, "eliminar", {"matricula": "2222CCC"}, "no_existe"),
                  "eliminar dos veces da error visible")

        # ── Detecciones ──
        mod_detector.SEGUNDOS_CIERRE_OBJETO = 0.05
        eventos: list[dict] = []
        hass.bus.async_listen("matriculas_detectada", lambda e: eventos.append(dict(e.data)))

        def lpr(plate: str, score: float, id_: str = "coche-1", camera: str = "Videoportero-Sub"):
            detector._al_mensaje(SimpleNamespace(payload=json.dumps(
                {"type": "lpr", "id": id_, "plate": plate, "score": score, "camera": camera,
                 "name": None, "timestamp": 0}
            )))

        lpr("3456RMX", 0.81)
        await hass.async_block_till_done()
        comprobar(len(eventos) == 1 and eventos[0]["tipo"] == "conocida"
                  and eventos[0]["nombre"] == "Fontanero" and eventos[0]["aproximada"],
                  "una lectura aproximada lanza matriculas_detectada con el nombre")
        comprobar(eventos and eventos[0]["abrir"] is True and eventos[0]["avisar"] is False,
                  "el evento lleva los permisos de la matrícula (abrir aunque sea aproximada)")
        estado = hass.states.get("event.matriculas_deteccion")
        comprobar(estado is not None and estado.attributes.get("event_type") == "conocida"
                  and estado.attributes.get("matricula") == "3456BMX",
                  "event.matriculas_deteccion refleja la detección")

        lpr("3456BMX", 0.92)
        lpr("3456BMX", 0.95)
        lpr("0000ZZZ", 0.99)
        await hass.async_block_till_done()
        comprobar(len(eventos) == 1,
                  f"el mismo coche no repite evento: misma identidad o lectura peor ({len(eventos)} eventos)")

        lpr("2468DFG", 0.70, id_="coche-2")
        lpr("1234BCD", 0.90, id_="coche-2")
        await hass.async_block_till_done()
        comprobar(len(eventos) == 3 and eventos[1]["tipo"] == "desconocida"
                  and eventos[2]["tipo"] == "conocida" and eventos[2]["nombre"] == "Abuela",
                  "de desconocido a conocido en el mismo coche sí lanza otro evento")

        lpr("1234BCD", 0.9, id_="coche-3", camera="Perimetral")
        detector._al_mensaje(SimpleNamespace(payload="no es json"))
        detector._al_mensaje(SimpleNamespace(payload=json.dumps({"type": "face", "id": "x"})))
        await hass.async_block_till_done()
        comprobar(len(eventos) == 3, "ignora otras cámaras, mensajes rotos y caras")

        await asyncio.sleep(0.2)
        await hass.async_block_till_done()
        vistas = almacen.vistas
        comprobar(vistas.get("3456BMX", {}).get("veces") == 1 and vistas.get("1234BCD", {}).get("veces") == 1,
                  f"al cerrar, cada coche cuenta una vez con su mejor identidad ({vistas})")
        comprobar("2468DFG" not in vistas, "la lectura mala previa del coche 2 no cuenta como desconocida")
        comprobar(len(almacen.historial) == 2 and almacen.historial[-1]["nombre"] == "Abuela",
                  "el historial guarda las detecciones cerradas")

        lpr("8642HJK", 0.8, id_="coche-4")
        lpr("8642HJK", 0.8, id_="coche-5")
        await asyncio.sleep(0.2)
        await hass.async_block_till_done()
        r = await _llamar(hass, "listar", {}, True)
        comprobar(r["desconocidas"] and r["desconocidas"][0]["matricula"] == "8642HJK"
                  and r["desconocidas"][0]["veces"] == 2,
                  "listar devuelve las desconocidas de más a menos frecuentes")
        comprobar([f["nombre"] for f in r["matriculas"]][:2] == ["Abuela", "Fontanero"],
                  "listar ordena por nombre")
        ficha = next(f for f in r["matriculas"] if f["matricula"] == "3456BMX")
        comprobar(ficha["vista"] and ficha["vista"]["veces"] == 1, "cada ficha trae sus estadísticas")

        # ── Importación manual: fichero roto no toca nada ──
        antes = json.dumps(almacen.matriculas, sort_keys=True)
        roto = directorio / "roto.json"
        roto.write_text('{"plates": {"1234BCD": ', "utf-8")
        comprobar(await _falla(hass, "importar", {"ruta": str(roto)}, "importar_ilegible"),
                  "un plates.json roto da error visible")
        comprobar(json.dumps(almacen.matriculas, sort_keys=True) == antes,
                  "y no cambia ni una matrícula (el sistema anterior las borraba todas)")

        # Fusionar conserva lo que el fichero no sabe (abrir, caducidad).
        await _llamar(hass, "editar", {"matricula": "1234BCD", "abrir": False})
        r = await _llamar(hass, "importar", {}, True)
        comprobar(r["sin_cambios"] == 4 and almacen.matriculas["1234BCD"]["abrir"] is False
                  and "7777NBW" in almacen.matriculas,
                  f"importar fusionando conserva «puede abrir» y las que no están en el fichero ({r})")
        r = await _llamar(hass, "importar", {"reemplazar": True}, True)
        comprobar(r["borradas"] == 1 and "7777NBW" not in almacen.matriculas,
                  "importar reemplazando borra las que no están en el fichero")

        # ── Persistencia tras recargar ──
        await _llamar(hass, "guardar", {"matricula": "1357CDF", "nombre": "Persistente", "notas": "hola"})
        assert await hass.config_entries.async_reload(entrada.entry_id)
        await hass.async_block_till_done()
        entrada = hass.config_entries.async_entries("matriculas")[0]
        nuevo = entrada.runtime_data.almacen
        comprobar(nuevo is not almacen and nuevo.matriculas.get("1357CDF", {}).get("notas") == "hola",
                  "las matrículas sobreviven a recargar la integración")
        comprobar(nuevo.vistas.get("8642HJK", {}).get("veces") == 2,
                  "las estadísticas también (se vuelcan al descargar)")
        comprobar(not nuevo.es_nuevo and "1234BCD" in nuevo.matriculas
                  and nuevo.matriculas["1234BCD"]["abrir"] is False,
                  "al recargar no se reimporta el plates.json")

        # ── Opciones ──
        r = await hass.config_entries.options.async_init(entrada.entry_id)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"prefijo_mqtt": "casa/frigate", "camaras": []}
        )
        await hass.async_block_till_done()
        entrada = hass.config_entries.async_entries("matriculas")[0]
        comprobar(entrada.runtime_data.detector.tema == "casa/frigate/tracked_object_update"
                  and not entrada.runtime_data.detector.camaras,
                  "cambiar las opciones recarga con el prefijo y las cámaras nuevas")

        # ── Sin entrada cargada ──
        await hass.config_entries.async_unload(entrada.entry_id)
        try:
            await _llamar(hass, "listar", {}, True)
            comprobar(False, "sin entrada cargada, los servicios dan error claro")
        except ServiceValidationError as err:
            comprobar(err.translation_key == "no_cargada",
                      "sin entrada cargada, los servicios dan error claro")
    finally:
        await hass.async_stop(force=True)


def test_home_assistant() -> None:
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        print("\nHome Assistant no instalado: se saltan las pruebas de integración")
        return

    print("\nIntegración en un Home Assistant real")
    directorio = Path(tempfile.mkdtemp(prefix="matriculas_"))
    try:
        (directorio / "custom_components").mkdir()
        (directorio / "custom_components" / "matriculas").symlink_to(
            RAIZ / "custom_components" / "matriculas"
        )
        asyncio.run(_recorrido(directorio))
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


if __name__ == "__main__":
    test_coincidencia()
    try:
        test_flujo_y_traducciones()
    except ImportError as err:
        print(f"\nSin Home Assistant ({err}): se salta flujo y traducciones")
    test_home_assistant()
    print()
    if fallos:
        print(f"{len(fallos)} FALLOS:")
        for f in fallos:
            print(f"  - {f}")
    else:
        print("Todo OK")
    # os._exit y no sys.exit: con HA 2026.9.2 y el Python 3.14.7 del venv, el
    # intérprete da un segfault al cerrarse si hay cualquier entrada de
    # configuración cargada (también con la integración oficial `sun`). Sin
    # esto, el código de salida sería 139 aunque todas las pruebas pasen.
    # Ver docs/DECISIONES.md §6.
    sys.stdout.flush()
    sys.stderr.flush()
    import os

    os._exit(1 if fallos else 0)
