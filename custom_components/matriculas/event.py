"""Entidad `event` con cada detección, para el historial y el diario."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EntradaMatriculas
from .const import SENAL_DETECCION, TIPOS_DETECCION
from .entity import EntidadMatriculas

ATRIBUTOS = (
    "matricula",
    "leida",
    "nombre",
    "aproximada",
    "metodo",
    "avisar",
    "abrir",
    "score",
    "camara",
    "frigate_id",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EntradaMatriculas,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([EventoDeteccion(entry)])


class EventoDeteccion(EntidadMatriculas, EventEntity):
    _attr_event_types = TIPOS_DETECCION

    def __init__(self, entry: EntradaMatriculas) -> None:
        super().__init__(entry, "event", "deteccion")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SENAL_DETECCION, self._al_detectar)
        )

    @callback
    def _al_detectar(self, evento: dict[str, Any]) -> None:
        self._trigger_event(evento["tipo"], {k: evento[k] for k in ATRIBUTOS})
        self.async_write_ha_state()
