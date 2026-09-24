"""Flujo de configuración de Matrículas."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_CAMARAS, CONF_PREFIJO_MQTT, DEFECTO_PREFIJO_MQTT, DOMAIN


def esquema(actual: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_PREFIJO_MQTT,
                default=actual.get(CONF_PREFIJO_MQTT, DEFECTO_PREFIJO_MQTT),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_CAMARAS, default=list(actual.get(CONF_CAMARAS, []))
            ): selector.TextSelector(selector.TextSelectorConfig(multiple=True)),
        }
    )


def limpiar(entrada: Mapping[str, Any]) -> dict[str, Any]:
    prefijo = str(entrada.get(CONF_PREFIJO_MQTT) or DEFECTO_PREFIJO_MQTT).strip().strip("/")
    camaras = [c.strip() for c in entrada.get(CONF_CAMARAS) or [] if c and c.strip()]
    return {CONF_PREFIJO_MQTT: prefijo or DEFECTO_PREFIJO_MQTT, CONF_CAMARAS: camaras}


class MatriculasConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(
                title="Matrículas", data={}, options=limpiar(user_input)
            )
        return self.async_show_form(step_id="user", data_schema=esquema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MatriculasOptionsFlow()


class MatriculasOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=limpiar(user_input))
        return self.async_show_form(
            step_id="init", data_schema=esquema(self.config_entry.options)
        )
