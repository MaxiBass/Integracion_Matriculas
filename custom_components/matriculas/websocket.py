"""Canal websocket del panel.

`matriculas/suscribir` manda al momento todo lo que el panel necesita y lo
vuelve a mandar cada vez que cambia el registro o las estadísticas. Las
ediciones no van por aquí: el panel llama a los servicios normales, que ya
validan y dan errores traducidos.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SENAL_ESTADISTICAS, SENAL_REGISTRO


@callback
def async_registrar(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_suscribir)


def _instantanea(hass: HomeAssistant) -> dict[str, Any] | None:
    # Se busca la entrada en cada envío: si se recarga, el almacén es otro.
    entradas = hass.config_entries.async_loaded_entries(DOMAIN)
    return entradas[0].runtime_data.almacen.instantanea() if entradas else None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/suscribir"})
@callback
def ws_suscribir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    datos = _instantanea(hass)
    if datos is None:
        connection.send_error(
            msg["id"], "no_cargada", "La integración Matrículas no está cargada"
        )
        return

    @callback
    def enviar() -> None:
        if (datos := _instantanea(hass)) is not None:
            connection.send_message(websocket_api.event_message(msg["id"], datos))

    desconectar = [
        async_dispatcher_connect(hass, SENAL_REGISTRO, enviar),
        async_dispatcher_connect(hass, SENAL_ESTADISTICAS, enviar),
    ]

    @callback
    def cancelar() -> None:
        for d in desconectar:
            d()

    connection.subscriptions[msg["id"]] = cancelar
    connection.send_result(msg["id"])
    connection.send_message(websocket_api.event_message(msg["id"], datos))
