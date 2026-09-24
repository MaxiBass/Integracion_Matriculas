"""Escucha las lecturas de matrícula de Frigate y las identifica.

Frigate publica en `<prefijo>/tracked_object_update` un mensaje `type: lpr`
por cada lectura de un coche que está siguiendo, y el mismo coche (mismo
`id`) puede llegar varias veces con lecturas y puntuaciones distintas.

Por cada coche se lanza `matriculas_detectada` la primera vez, y otra vez
solo si una lectura posterior lo identifica mejor: de desconocido a conocido,
o con otra matrícula del mismo tipo pero más puntuación. Pasados
`SEGUNDOS_CIERRE_OBJETO` sin lecturas nuevas, el coche se da por cerrado y
se anota una sola vez en las estadísticas, con la mejor identificación.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from . import coincidencia
from .almacen import Almacen
from .const import (
    CADUCADA,
    CONOCIDA,
    EVENTO_DETECTADA,
    SEGUNDOS_CIERRE_OBJETO,
    SENAL_DETECCION,
)

_LOGGER = logging.getLogger(__name__)

# Qué identificación es mejor que otra para el mismo coche.
_RANGO = {CONOCIDA: 2, CADUCADA: 1}


@dataclass
class _Coche:
    evento: dict[str, Any]
    cancelar_cierre: Callable[[], None] | None = field(default=None, repr=False)

    @property
    def rango(self) -> int:
        return _RANGO.get(self.evento["tipo"], 0)


def _puntuacion(valor: Any) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


class Detector:
    """Suscripción a Frigate y deduplicación por coche."""

    def __init__(
        self, hass: HomeAssistant, almacen: Almacen, prefijo: str, camaras: list[str]
    ) -> None:
        self.hass = hass
        self.almacen = almacen
        self.tema = f"{prefijo}/tracked_object_update"
        self.camaras = set(camaras)
        self._coches: dict[str, _Coche] = {}
        self._desuscribir: Callable[[], None] | None = None

    async def async_iniciar(self) -> None:
        # Import diferido: MQTT es opcional (after_dependencies). Sin MQTT la
        # integración sigue sirviendo para gestionar matrículas.
        from homeassistant.components import mqtt

        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            _LOGGER.warning(
                "MQTT no está disponible: no se recibirán lecturas de Frigate. "
                "La gestión de matrículas sigue funcionando"
            )
            return
        self._desuscribir = await mqtt.async_subscribe(
            self.hass, self.tema, self._al_mensaje
        )
        _LOGGER.debug("Escuchando %s", self.tema)

    async def async_parar(self) -> None:
        if self._desuscribir:
            self._desuscribir()
            self._desuscribir = None
        for clave in list(self._coches):
            self._cerrar(clave)

    @callback
    def _al_mensaje(self, mensaje: Any) -> None:
        try:
            datos = json.loads(mensaje.payload)
        except (TypeError, ValueError):
            return
        if isinstance(datos, dict) and datos.get("type") == "lpr":
            self.procesar(datos)

    @callback
    def procesar(self, datos: dict[str, Any]) -> dict[str, Any] | None:
        """Procesa una lectura. Devuelve el evento lanzado, o None."""
        camara = str(datos.get("camera") or "")
        if self.camaras and camara not in self.camaras:
            return None
        leida = coincidencia.normalizar(datos.get("plate") or "")
        if not leida:
            return None

        frigate_id = str(datos.get("id") or "")
        evento = {
            **self.almacen.resolver(leida),
            "score": _puntuacion(datos.get("score")),
            "camara": camara,
            "frigate_id": frigate_id,
            "hora": dt_util.utcnow().isoformat(),
        }
        clave = frigate_id or f"sin_id_{uuid4().hex}"
        nuevo = _Coche(evento)
        previo = self._coches.get(clave)

        if previo is not None:
            misma = (nuevo.evento["tipo"], nuevo.evento["matricula"]) == (
                previo.evento["tipo"], previo.evento["matricula"]
            )
            mejora = nuevo.rango > previo.rango or (
                nuevo.rango == previo.rango and evento["score"] > previo.evento["score"]
            )
            if misma or not mejora:
                if misma and evento["score"] > previo.evento["score"]:
                    previo.evento["score"] = evento["score"]
                self._programar_cierre(clave, previo)
                return None
            if previo.cancelar_cierre:
                previo.cancelar_cierre()

        self._coches[clave] = nuevo
        self._programar_cierre(clave, nuevo)
        self.hass.bus.async_fire(EVENTO_DETECTADA, evento)
        async_dispatcher_send(self.hass, SENAL_DETECCION, evento)
        return evento

    @callback
    def _programar_cierre(self, clave: str, coche: _Coche) -> None:
        if coche.cancelar_cierre:
            coche.cancelar_cierre()

        @callback
        def _al_vencer(_ahora: Any) -> None:
            coche.cancelar_cierre = None
            self._cerrar(clave)

        coche.cancelar_cierre = async_call_later(
            self.hass, SEGUNDOS_CIERRE_OBJETO, _al_vencer
        )

    @callback
    def _cerrar(self, clave: str) -> None:
        coche = self._coches.pop(clave, None)
        if coche is None:
            return
        if coche.cancelar_cierre:
            coche.cancelar_cierre()
        e = coche.evento
        self.almacen.anotar_deteccion(
            {
                "hora": e["hora"],
                "matricula": e["matricula"],
                "leida": e["leida"],
                "tipo": e["tipo"],
                "nombre": e["nombre"],
                "aproximada": e["aproximada"],
                "score": e["score"],
                "camara": e["camara"],
                "frigate_id": e["frigate_id"],
            }
        )
