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


def test_sugerencias() -> None:
    import importlib.util

    ruta = RAIZ / "custom_components" / "matriculas" / "sugerencias.py"
    spec = importlib.util.spec_from_file_location("sugerencias", ruta)
    su = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(su)

    print("\nSugerencias — matrículas mal guardadas")

    reg = {"1234BCD": {"nombre": "Abuela"}}
    vistas = lambda lect: {"1234BCD": {"lecturas": lect}}  # noqa: E731

    r = su.calcular(reg, vistas({"1234BCF": 2}))
    comprobar(list(r) == ["correccion_1234bcd_1234bcf"] and r["correccion_1234bcd_1234bcf"]["propuesta"] == "1234BCF",
              "leída 2 veces como otra y nunca como la guardada → sugiere corregir")
    comprobar(not su.calcular(reg, vistas({"1234BCF": 1})), "una sola lectura distinta no basta (los errores sueltos son normales)")
    comprobar(not su.calcular(reg, vistas({"1234BCD": 3, "1234BCF": 2})), "si la guardada se lee más, no sugiere nada")
    comprobar(bool(su.calcular(reg, vistas({"1234BCD": 1, "1234BCF": 3}))), "si la otra domina, sí")
    r = su.calcular({**reg, "1234BCF": {"nombre": "X"}}, vistas({"1234BCF": 3}))
    comprobar(not any(k.startswith("correccion") for k in r) and "duplicado_1234bcd_1234bcf" in r,
              "si la otra ya está registrada, no es una corrección sino un posible duplicado")
    comprobar(not su.calcular(reg, vistas({"1234BCF": 3}), ["correccion_1234bcd_1234bcf"]), "las descartadas no vuelven")

    dup = su.calcular({"0123KNN": {"nombre": "L"}, "0123KNW": {"nombre": "L2"}},
                      {"0123KNW": {"lecturas": {"0123KNW": 2}}})
    d = dup.get("duplicado_0123knn_0123knw", {})
    comprobar(d.get("sobra") == "0123KNN", "dos registradas a un carácter → duplicado; sobra la que nunca se lee")
    comprobar(not su.calcular({"1234BCD": {"nombre": "A"}, "1234BFF": {"nombre": "B"}}, {}),
              "a dos caracteres no es duplicado")

    lecturas = {f"000{i}AAA": 5 for i in range(8)}
    su.anotar_lectura(lecturas, "9999ZZZ")
    comprobar(len(lecturas) == su.MAX_LECTURAS and "9999ZZZ" in lecturas,
              "las lecturas no crecen sin límite y nunca se pierde la recién anotada")


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


class _ConexionWs:
    """Lo mínimo de una conexión websocket para llamar al comando directamente."""

    def __init__(self) -> None:
        self.mensajes: list[dict] = []
        self.subscriptions: dict = {}

    def send_message(self, mensaje: dict) -> None:
        self.mensajes.append(mensaje)

    def send_result(self, iden: int, resultado=None) -> None:
        self.mensajes.append({"id": iden, "type": "result", "success": True})

    def send_error(self, iden: int, codigo: str, mensaje: str, **_kw) -> None:
        self.mensajes.append({"id": iden, "type": "result", "success": False, "code": codigo})

    def eventos(self) -> list[dict]:
        return [m["event"] for m in self.mensajes if m.get("type") == "event"]


def _panel(hass):
    from homeassistant.components.frontend import DATA_PANELS

    return hass.data.get(DATA_PANELS, {}).get("matriculas")


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

        # ── Panel ──
        panel = _panel(hass)
        comprobar(panel is not None and panel.sidebar_title == "Matrículas" and not panel.require_admin,
                  "registra el panel «Matrículas» en la barra lateral, para todos los usuarios")
        version = json.loads((RAIZ / "custom_components/matriculas/manifest.json").read_text("utf-8"))["version"]
        url = (panel.config or {}).get("_panel_custom", {}).get("module_url", "") if panel else ""
        comprobar(url.endswith(f"matriculas-panel.js?v={version}"),
                  f"el JS del panel lleva la versión en la URL para no quedarse en caché ({url})")
        comprobar((RAIZ / "custom_components/matriculas/frontend/matriculas-panel.js").is_file(),
                  "el fichero del panel existe donde se sirve")

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
        await _llamar(hass, "editar", {"matricula": "7777NBW", "caduca": ""})
        comprobar(almacen.matriculas["7777NBW"]["caduca"] is None, "una caducidad vacía la quita (lo que manda el panel)")
        await _llamar(hass, "editar", {"matricula": "7777NBW", "caduca": "2020-01-01"})

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

        # ── Websocket del panel ──
        from custom_components.matriculas.websocket import ws_suscribir

        ws = _ConexionWs()
        ws_suscribir(hass, ws, {"id": 7, "type": "matriculas/suscribir"})
        inicial = ws.eventos()
        comprobar(ws.mensajes[0].get("success") is True and len(inicial) == 1,
                  "suscribirse responde bien y manda los datos al momento")
        comprobar(inicial and {"matriculas", "desconocidas", "ignoradas", "historial"} <= set(inicial[0])
                  and len(inicial[0]["matriculas"]) == len(almacen.matriculas),
                  "los datos traen registradas, desconocidas, ignoradas e historial")
        comprobar(inicial and inicial[0]["historial"][0]["matricula"] == "8642HJK",
                  "el historial llega del más reciente al más antiguo")
        comprobar(almacen.vistas["8642HJK"].get("frigate_id") == "coche-5",
                  "cada matrícula guarda el id de Frigate de la última vez (para la foto)")

        await _llamar(hass, "guardar", {"matricula": "1122BBC", "nombre": "Por websocket"})
        comprobar(len(ws.eventos()) == 2 and any(f["matricula"] == "1122BBC" for f in ws.eventos()[-1]["matriculas"]),
                  "al guardar, el panel recibe los datos nuevos sin pedirlos")
        lpr("1122BBC", 0.9, id_="coche-ws")
        await asyncio.sleep(0.2)
        await hass.async_block_till_done()
        ultimo = ws.eventos()[-1]
        comprobar(ultimo["historial"][0]["nombre"] == "Por websocket",
                  "al cerrarse una detección, el panel recibe el historial actualizado")
        antes_ws = len(ws.mensajes)
        ws.subscriptions[7]()
        await _llamar(hass, "eliminar", {"matricula": "1122BBC"})
        comprobar(len(ws.mensajes) == antes_ws, "al cancelar la suscripción deja de recibir")

        # ── Matrículas mal guardadas ──
        from homeassistant.components.repairs import repairs_flow_manager
        from homeassistant.helpers import issue_registry as ir

        avisos_ev: list[dict] = []
        hass.bus.async_listen("matriculas_sugerencia", lambda e: avisos_ev.append(dict(e.data)))
        issues = ir.async_get(hass)

        def aviso(ident):
            return issues.async_get_issue("matriculas", ident)

        await _llamar(hass, "guardar", {"matricula": "4680DFG", "nombre": "Primo", "abrir": False, "notas": "n"})
        for i in range(2):  # dos visitas en las que Frigate lee DFH
            lpr("4680DFH", 0.9, id_=f"primo-{i}")
            await asyncio.sleep(0.15)
        await hass.async_block_till_done()
        ident = "correccion_4680dfg_4680dfh"
        comprobar(almacen.vistas["4680DFG"]["lecturas"] == {"4680DFH": 2}, "cuenta cómo la lee Frigate en cada visita")
        comprobar(ident in almacen.sugerencias, "2 visitas leída como otra → sugerencia de corrección")
        comprobar(aviso(ident) is not None and aviso(ident).translation_key == "correccion" and aviso(ident).is_fixable,
                  "aparece en Ajustes → Reparaciones, con arreglo")
        comprobar(aviso(ident) and aviso(ident).translation_placeholders.get("propuesta") == "4680 DFH",
                  "el aviso muestra la matrícula propuesta con formato")
        comprobar([e["id"] for e in avisos_ev] == [ident], "lanza matriculas_sugerencia una vez")
        comprobar(hass.states.get("sensor.matriculas_registradas").attributes.get("sugerencias") == 1,
                  "el sensor cuenta las sugerencias")
        lpr("4680DFH", 0.9, id_="primo-2")
        await asyncio.sleep(0.15)
        await hass.async_block_till_done()
        comprobar(len(avisos_ev) == 1 and aviso(ident).translation_placeholders["veces_propuesta"] == "3",
                  "otra visita actualiza las cifras del aviso sin repetir el evento")

        # Arreglo desde Reparaciones: menú → corregir
        fm = repairs_flow_manager(hass)
        r = await fm.async_init("matriculas", data={"issue_id": ident})
        comprobar(r["type"] == "menu" and list(r["menu_options"]) == ["corregir", "otro_coche", "descartar"],
                  f"el arreglo ofrece corregir, otro coche o descartar ({r.get('type')})")
        r = await fm.async_configure(r["flow_id"], {"next_step_id": "corregir"})
        await hass.async_block_till_done()
        ficha = almacen.matriculas.get("4680DFH", {})
        comprobar(r["type"] == "create_entry" and "4680DFG" not in almacen.matriculas
                  and ficha.get("nombre") == "Primo" and ficha.get("abrir") is False and ficha.get("notas") == "n",
                  "corregir renombra conservando nombre y permisos")
        comprobar(almacen.vistas.get("4680DFH", {}).get("veces") == 3, "y las estadísticas")
        comprobar(aviso(ident) is None and not almacen.sugerencias, "el aviso desaparece")

        # «Es otro coche»: se registra aparte, sin abrir, y no aparece como duplicado
        await _llamar(hass, "guardar", {"matricula": "5791FGH", "nombre": "Tía"})
        for i in range(2):
            lpr("5791FGJ", 0.9, id_=f"tia-{i}")
            await asyncio.sleep(0.15)
        await hass.async_block_till_done()
        ident2 = "correccion_5791fgh_5791fgj"
        antes_ev = len(avisos_ev)
        await _llamar(hass, "resolver_sugerencia", {"id": ident2, "accion": "otro_coche", "nombre": "Casa del 5"})
        otro = almacen.matriculas.get("5791FGJ", {})
        comprobar(otro.get("nombre") == "Casa del 5" and otro.get("avisar") is True and otro.get("abrir") is False,
                  "«es otro coche» lo registra aparte: avisa, pero no abre por defecto")
        comprobar(not almacen.sugerencias and len(avisos_ev) == antes_ev and aviso("duplicado_5791fgh_5791fgj") is None,
                  "y no lo vuelve a presentar como duplicado de la otra")
        lpr("5791FGJ", 0.9, id_="tia-2")
        await asyncio.sleep(0.15)
        await hass.async_block_till_done()
        comprobar(almacen.vistas.get("5791FGJ", {}).get("veces") == 1, "desde entonces se le reconoce como él mismo")

        # Duplicado: dos casi iguales
        await _llamar(hass, "guardar", {"matricula": "6802GHJ", "nombre": "Laura"})
        await _llamar(hass, "guardar", {"matricula": "6802GHK", "nombre": "Laura bis"})
        ident3 = "duplicado_6802ghj_6802ghk"
        comprobar(aviso(ident3) is not None and aviso(ident3).translation_key == "duplicado",
                  "dos registradas a un carácter → aviso de duplicado")
        r = await fm.async_init("matriculas", data={"issue_id": ident3})
        comprobar(list(r["menu_options"]) == ["eliminar_primera", "eliminar_segunda", "descartar"],
                  "el arreglo ofrece eliminar una u otra, o descartar")
        r = await fm.async_configure(r["flow_id"], {"next_step_id": "eliminar_segunda"})
        comprobar("6802GHK" not in almacen.matriculas and "6802GHJ" in almacen.matriculas and aviso(ident3) is None,
                  "eliminar la segunda la borra y quita el aviso")

        # Descartar: no vuelve, ni tras recargar
        await _llamar(hass, "guardar", {"matricula": "6802GHK", "nombre": "Otra Laura"})
        await _llamar(hass, "resolver_sugerencia", {"id": ident3, "accion": "descartar"})
        comprobar(aviso(ident3) is None and ident3 in almacen.descartadas, "descartar quita el aviso y lo recuerda")
        comprobar(await _falla(hass, "resolver_sugerencia", {"id": ident3, "accion": "descartar"}, "sugerencia_no_existe"),
                  "una sugerencia ya resuelta da error claro")

        # Reconstrucción de lecturas para datos de versiones anteriores
        del almacen.vistas["1234BCD"]["lecturas"]
        almacen._reconstruir_lecturas()
        comprobar(almacen.vistas["1234BCD"]["lecturas"] == {"1234BCD": 1},
                  "las lecturas de datos antiguos se reconstruyen desde el historial")

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
        sobran = set(almacen.matriculas) - {"1234BCD", "5678FGH", "9012JKL", "3456BMX"}
        r = await _llamar(hass, "importar", {"reemplazar": True}, True)
        comprobar(r["borradas"] == len(sobran) and "7777NBW" not in almacen.matriculas
                  and set(almacen.matriculas) == {"1234BCD", "5678FGH", "9012JKL", "3456BMX"},
                  f"importar reemplazando borra las que no están en el fichero ({r['borradas']})")

        # Un duplicado vivo, para comprobar la recarga
        await _llamar(hass, "guardar", {"matricula": "7913HJK", "nombre": "Pendiente"})
        await _llamar(hass, "guardar", {"matricula": "7913HJL", "nombre": "Pendiente bis"})
        await hass.async_block_till_done()  # el evento llega a los oyentes un instante después
        eventos_antes_recarga = len(avisos_ev)

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
        comprobar(aviso("duplicado_7913hjk_7913hjl") is not None and len(avisos_ev) == eventos_antes_recarga,
                  f"al recargar, el aviso sigue ahí y el evento no se repite ({eventos_antes_recarga}→{len(avisos_ev)})")
        comprobar("duplicado_6802ghj_6802ghk" in nuevo.descartadas, "las descartadas sobreviven a la recarga")
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

        comprobar(_panel(hass) is not None, "tras recargar, el panel sigue registrado")

        # ── Sin entrada cargada ──
        await hass.config_entries.async_unload(entrada.entry_id)
        comprobar(_panel(hass) is None, "al descargar la integración se quita el panel")
        comprobar(not [i for (d, i) in issues.issues if d == "matriculas"],
                  "y sus avisos de Reparaciones (sin ella no se pueden resolver)")
        ws = _ConexionWs()
        ws_suscribir(hass, ws, {"id": 8, "type": "matriculas/suscribir"})
        comprobar(ws.mensajes and ws.mensajes[0].get("code") == "no_cargada",
                  "sin entrada cargada, el websocket da un error claro")
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
    test_sugerencias()
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
