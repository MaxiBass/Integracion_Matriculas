"""Matrículas — registro y reconocimiento de matrículas con Frigate."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .almacen import SIN_CAMBIO, Almacen
from .const import (
    CONF_CAMARAS,
    CONF_PREFIJO_MQTT,
    DEFECTO_PREFIJO_MQTT,
    DOMAIN,
    ELEMENTO_PANEL,
    FICHERO_PANEL,
    RUTA_ESTATICA,
    RUTA_LEGADO,
    URL_PANEL,
)
from .detector import Detector
from .websocket import async_registrar as async_registrar_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.EVENT, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICIO_GUARDAR = "guardar"
SERVICIO_EDITAR = "editar"
SERVICIO_ELIMINAR = "eliminar"
SERVICIO_IGNORAR = "ignorar"
SERVICIO_DEJAR_DE_IGNORAR = "dejar_de_ignorar"
SERVICIO_BUSCAR = "buscar"
SERVICIO_LISTAR = "listar"
SERVICIO_IMPORTAR = "importar"
SERVICIO_RESOLVER_SUGERENCIA = "resolver_sugerencia"

_FECHA_O_VACIO = vol.Any(None, "", cv.date)

ESQUEMA_MATRICULA = vol.Schema({vol.Required("matricula"): cv.string})
ESQUEMA_GUARDAR = vol.Schema(
    {
        vol.Required("matricula"): cv.string,
        vol.Required("nombre"): cv.string,
        vol.Optional("avisar"): cv.boolean,
        vol.Optional("abrir"): cv.boolean,
        vol.Optional("notas"): cv.string,
        vol.Optional("caduca"): _FECHA_O_VACIO,
    }
)
ESQUEMA_EDITAR = vol.Schema(
    {
        vol.Required("matricula"): cv.string,
        vol.Optional("nueva_matricula"): cv.string,
        vol.Optional("nombre"): cv.string,
        vol.Optional("avisar"): cv.boolean,
        vol.Optional("abrir"): cv.boolean,
        vol.Optional("notas"): cv.string,
        vol.Optional("caduca"): _FECHA_O_VACIO,
    }
)
ESQUEMA_RESOLVER_SUGERENCIA = vol.Schema(
    {
        vol.Required("id"): cv.string,
        vol.Required("accion"): vol.In(["corregir", "otro_coche", "eliminar", "descartar"]),
        vol.Optional("matricula"): cv.string,
        vol.Optional("nombre"): cv.string,
        vol.Optional("avisar"): cv.boolean,
        vol.Optional("abrir"): cv.boolean,
        vol.Optional("notas"): cv.string,
        vol.Optional("caduca"): _FECHA_O_VACIO,
    }
)
ESQUEMA_IMPORTAR = vol.Schema(
    {
        vol.Optional("ruta"): cv.string,
        vol.Optional("reemplazar", default=False): cv.boolean,
    }
)


@dataclass
class DatosMatriculas:
    almacen: Almacen
    detector: Detector


type EntradaMatriculas = ConfigEntry[DatosMatriculas]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra servicios y websocket, que existen aunque la entrada no cargue."""
    _registrar_servicios(hass)
    async_registrar_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EntradaMatriculas) -> bool:
    almacen = Almacen(hass)
    await almacen.async_cargar()

    if almacen.es_nuevo:
        ruta = hass.config.path(RUTA_LEGADO)
        if await hass.async_add_executor_job(os.path.isfile, ruta):
            try:
                await almacen.async_importar(ruta)
            except ServiceValidationError as err:
                # Sin guardar nada: el próximo arranque lo vuelve a intentar.
                _LOGGER.error("No se pudo importar %s: %s", ruta, err)
    almacen.recalcular_sugerencias(inicio=True)

    opciones = {**entry.data, **entry.options}
    detector = Detector(
        hass,
        almacen,
        opciones.get(CONF_PREFIJO_MQTT, DEFECTO_PREFIJO_MQTT),
        opciones.get(CONF_CAMARAS, []),
    )
    entry.runtime_data = DatosMatriculas(almacen, detector)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_registrar_panel(hass)

    # En segundo plano: esperar a MQTT no debe retrasar el arranque de HA.
    entry.async_create_background_task(
        hass, detector.async_iniciar(), f"{DOMAIN}_suscripcion_frigate"
    )
    entry.async_on_unload(entry.add_update_listener(_al_actualizar_opciones))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EntradaMatriculas) -> bool:
    descargada = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if descargada:
        frontend.async_remove_panel(hass, URL_PANEL, warn_if_unknown=False)
        await entry.runtime_data.detector.async_parar()
        entry.runtime_data.almacen.quitar_avisos()
        await entry.runtime_data.almacen.async_volcar()
    return descargada


async def _async_registrar_panel(hass: HomeAssistant) -> None:
    """Panel "Matrículas" en la barra lateral, para todos los usuarios."""
    if not hass.data.get(f"{DOMAIN}_ruta_estatica"):
        # Una ruta estática no se puede quitar: se registra una sola vez.
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    f"{RUTA_ESTATICA}/{FICHERO_PANEL}",
                    str(Path(__file__).parent / "frontend" / FICHERO_PANEL),
                    cache_headers=False,
                )
            ]
        )
        hass.data[f"{DOMAIN}_ruta_estatica"] = True

    # La versión en la URL obliga al navegador a descargar el JS nuevo al
    # actualizar la integración.
    version = (await async_get_integration(hass, DOMAIN)).version
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=URL_PANEL,
        webcomponent_name=ELEMENTO_PANEL,
        sidebar_title="Matrículas",
        sidebar_icon="mdi:car-search",
        module_url=f"{RUTA_ESTATICA}/{FICHERO_PANEL}?v={version}",
        require_admin=False,
    )


async def _al_actualizar_opciones(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _almacen(hass: HomeAssistant) -> Almacen:
    entradas = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entradas:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_cargada"
        )
    return entradas[0].runtime_data.almacen


def _registrar_servicios(hass: HomeAssistant) -> None:
    async def guardar(call: ServiceCall) -> ServiceResponse:
        d = call.data
        ficha, nueva = await _almacen(hass).async_guardar(
            d["matricula"],
            d["nombre"],
            avisar=d.get("avisar"),
            abrir=d.get("abrir"),
            notas=d.get("notas"),
            caduca=d.get("caduca", SIN_CAMBIO),
        )
        return {"ficha": ficha, "nueva": nueva}

    async def editar(call: ServiceCall) -> ServiceResponse:
        d = call.data
        ficha = await _almacen(hass).async_editar(
            d["matricula"],
            nueva_matricula=d.get("nueva_matricula"),
            nombre=d.get("nombre"),
            avisar=d.get("avisar"),
            abrir=d.get("abrir"),
            notas=d.get("notas"),
            caduca=d.get("caduca", SIN_CAMBIO),
        )
        return {"ficha": ficha}

    async def eliminar(call: ServiceCall) -> None:
        await _almacen(hass).async_eliminar(call.data["matricula"])

    async def ignorar(call: ServiceCall) -> None:
        await _almacen(hass).async_ignorar(call.data["matricula"])

    async def dejar_de_ignorar(call: ServiceCall) -> None:
        await _almacen(hass).async_dejar_de_ignorar(call.data["matricula"])

    async def buscar(call: ServiceCall) -> ServiceResponse:
        almacen = _almacen(hass)
        resultado: dict[str, Any] = almacen.resolver(call.data["matricula"])
        if resultado["matricula"] in almacen.matriculas:
            resultado["ficha"] = almacen.ficha(resultado["matricula"])
        return resultado

    async def listar(call: ServiceCall) -> ServiceResponse:
        return _almacen(hass).instantanea()

    async def resolver_sugerencia(call: ServiceCall) -> None:
        d = call.data
        await _almacen(hass).async_resolver_sugerencia(
            d["id"],
            d["accion"],
            matricula=d.get("matricula"),
            nombre=d.get("nombre"),
            avisar=d.get("avisar"),
            abrir=d.get("abrir"),
            notas=d.get("notas"),
            caduca=d.get("caduca", SIN_CAMBIO),
        )

    async def importar(call: ServiceCall) -> ServiceResponse:
        ruta = call.data.get("ruta") or hass.config.path(RUTA_LEGADO)
        return await _almacen(hass).async_importar(
            ruta, reemplazar=call.data["reemplazar"]
        )

    registro = hass.services.async_register
    registro(DOMAIN, SERVICIO_GUARDAR, guardar, ESQUEMA_GUARDAR, SupportsResponse.OPTIONAL)
    registro(DOMAIN, SERVICIO_EDITAR, editar, ESQUEMA_EDITAR, SupportsResponse.OPTIONAL)
    registro(DOMAIN, SERVICIO_ELIMINAR, eliminar, ESQUEMA_MATRICULA)
    registro(DOMAIN, SERVICIO_IGNORAR, ignorar, ESQUEMA_MATRICULA)
    registro(DOMAIN, SERVICIO_DEJAR_DE_IGNORAR, dejar_de_ignorar, ESQUEMA_MATRICULA)
    registro(DOMAIN, SERVICIO_BUSCAR, buscar, ESQUEMA_MATRICULA, SupportsResponse.ONLY)
    registro(DOMAIN, SERVICIO_LISTAR, listar, vol.Schema({}), SupportsResponse.ONLY)
    registro(DOMAIN, SERVICIO_IMPORTAR, importar, ESQUEMA_IMPORTAR, SupportsResponse.OPTIONAL)
    registro(DOMAIN, SERVICIO_RESOLVER_SUGERENCIA, resolver_sugerencia, ESQUEMA_RESOLVER_SUGERENCIA)
