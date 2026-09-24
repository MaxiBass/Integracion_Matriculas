"""Base común de las entidades de Matrículas."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class EntidadMatriculas(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, plataforma: str, clave: str) -> None:
        # entity_id fijo: las automatizaciones lo usan, y el que HA genera a
        # partir del nombre traducido depende del idioma de la instalación.
        self.entity_id = f"{plataforma}.{DOMAIN}_{clave}"
        self._attr_unique_id = f"{entry.entry_id}_{clave}"
        self._attr_translation_key = clave
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Matrículas",
            manufacturer="Matrículas",
            model="Reconocimiento de matrículas con Frigate",
            entry_type=DeviceEntryType.SERVICE,
        )
