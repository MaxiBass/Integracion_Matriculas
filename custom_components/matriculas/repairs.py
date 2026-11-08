"""Arreglo de las sugerencias desde Ajustes → Reparaciones.

Mismas opciones que en el panel. Al terminar, HA borra el aviso; la
integración también lo borra al recalcular, y borrar dos veces no es un
error.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from . import sugerencias
from . import almacen_cargado
from .almacen import Almacen, _validar_nombre, marcadores_sugerencia


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    return ArreglarSugerencia(issue_id)


class ArreglarSugerencia(RepairsFlow):
    def __init__(self, ident: str) -> None:
        self._ident = ident

    def _almacen(self) -> Almacen | None:
        return almacen_cargado(self.hass)

    def _sugerencia(self) -> dict[str, Any] | None:
        almacen = self._almacen()
        return almacen.sugerencias.get(self._ident) if almacen else None

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        s = self._sugerencia()
        if s is None:
            return self.async_abort(reason="ya_resuelta")
        opciones = (
            ["corregir", "otro_coche", "descartar"]
            if s["tipo"] == sugerencias.CORRECCION
            else ["eliminar_primera", "eliminar_segunda", "descartar"]
        )
        return self.async_show_menu(
            step_id="init",
            menu_options=opciones,
            description_placeholders=marcadores_sugerencia(s),
        )

    async def _resolver(self, accion: str, **kw: Any) -> data_entry_flow.FlowResult:
        almacen = self._almacen()
        if almacen is None or self._ident not in almacen.sugerencias:
            return self.async_abort(reason="ya_resuelta")
        try:
            await almacen.async_resolver_sugerencia(self._ident, accion, **kw)
        except ServiceValidationError as err:
            # Por ejemplo, corregir a una matrícula que alguien acaba de
            # registrar: se dice por qué en vez de un error sin explicar.
            return self.async_abort(
                reason="no_se_pudo",
                description_placeholders={"error": str(err) or err.translation_key or type(err).__name__},
            )
        return self.async_create_entry(data={})

    async def async_step_corregir(self, user_input=None) -> data_entry_flow.FlowResult:
        return await self._resolver("corregir")

    async def async_step_descartar(self, user_input=None) -> data_entry_flow.FlowResult:
        return await self._resolver("descartar")

    async def async_step_eliminar_primera(self, user_input=None) -> data_entry_flow.FlowResult:
        s = self._sugerencia()
        return await self._resolver("eliminar", matricula=s["matricula"] if s else "")

    async def async_step_eliminar_segunda(self, user_input=None) -> data_entry_flow.FlowResult:
        s = self._sugerencia()
        return await self._resolver("eliminar", matricula=s["otra"] if s else "")

    async def async_step_otro_coche(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        s = self._sugerencia()
        if s is None:
            return self.async_abort(reason="ya_resuelta")
        errores: dict[str, str] = {}
        if user_input is not None:
            try:
                _validar_nombre(user_input["nombre"])
            except ServiceValidationError:
                errores["nombre"] = "nombre_vacio"
            else:
                return await self._resolver(
                    "otro_coche",
                    nombre=user_input["nombre"],
                    avisar=user_input["avisar"],
                    abrir=user_input["abrir"],
                )
        return self.async_show_form(
            step_id="otro_coche",
            data_schema=vol.Schema(
                {
                    vol.Required("nombre"): str,
                    vol.Required("avisar", default=True): bool,
                    vol.Required("abrir", default=False): bool,
                }
            ),
            errors=errores,
            description_placeholders=marcadores_sugerencia(s),
        )
