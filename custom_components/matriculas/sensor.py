"""Sensor con el número de matrículas registradas."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EntradaMatriculas
from .almacen import Almacen, caducada
from .const import SENAL_ESTADISTICAS, SENAL_REGISTRO
from .entity import EntidadMatriculas


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EntradaMatriculas,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SensorRegistradas(entry, entry.runtime_data.almacen)])


class SensorRegistradas(EntidadMatriculas, SensorEntity):
    """Solo cuentas: la lista completa se pide con `matriculas.listar`, para
    no llenar el historial con atributos grandes."""

    def __init__(self, entry: EntradaMatriculas, almacen: Almacen) -> None:
        super().__init__(entry, "sensor", "registradas")
        self._almacen = almacen

    async def async_added_to_hass(self) -> None:
        # Las sugerencias cambian también con las detecciones.
        for senal in (SENAL_REGISTRO, SENAL_ESTADISTICAS):
            self.async_on_remove(
                async_dispatcher_connect(self.hass, senal, self._al_cambiar)
            )

    @callback
    def _al_cambiar(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return len(self._almacen.matriculas)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hoy = dt_util.now().date()
        return {
            "ignoradas": len(self._almacen.ignoradas),
            "sugerencias": len(self._almacen.sugerencias),
            "caducadas": sum(
                caducada(d, hoy) for d in self._almacen.matriculas.values()
            ),
        }
