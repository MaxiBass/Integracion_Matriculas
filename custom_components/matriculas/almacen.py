"""Registro de matrículas y de sus detecciones.

Dos ficheros en `.storage/`:

- `matriculas.registro`: matrículas conocidas e ignoradas. Solo se escribe
  cuando alguien edita, y siempre de forma atómica.
- `matriculas.detecciones`: estadísticas por matrícula e historial reciente.
  Se escribe con retardo porque cambia a menudo.

Si HA encuentra uno de los dos corrupto al arrancar, lo aparta como
`.corrupt.<fecha>` y abre un aviso en Reparaciones: nunca se sobrescribe en
silencio, que es justo lo que hacían los scripts `save_plate.py` y
`update_plate.py` del sistema anterior.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import coincidencia
from .const import (
    CADUCADA,
    CLAVE_DETECCIONES,
    CLAVE_REGISTRO,
    CONOCIDA,
    DESCONOCIDA,
    DOMAIN,
    HISTORIAL_PANEL,
    IGNORADA,
    LONGITUD_MAXIMA,
    LONGITUD_MAXIMA_NOMBRE,
    LONGITUD_MINIMA,
    MAX_HISTORIAL,
    SEGUNDOS_GUARDADO_DETECCIONES,
    SENAL_ESTADISTICAS,
    SENAL_REGISTRO,
    VERSION_ALMACEN,
)

_LOGGER = logging.getLogger(__name__)

# Distingue "no tocar este campo" de "vaciarlo" (None) en las ediciones.
SIN_CAMBIO: Any = object()


def _error(clave: str, **marcadores: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=clave,
        translation_placeholders=marcadores or None,
    )


def validar_matricula(texto: str) -> str:
    """Normaliza y valida una matrícula tecleada por una persona."""
    matricula = coincidencia.normalizar(texto)
    if not LONGITUD_MINIMA <= len(matricula) <= LONGITUD_MAXIMA:
        raise _error("matricula_invalida", matricula=str(texto))
    return matricula


def _validar_nombre(texto: str) -> str:
    nombre = " ".join(str(texto).split())
    if not nombre:
        raise _error("nombre_vacio")
    return nombre[:LONGITUD_MAXIMA_NOMBRE]


def _fecha(valor: Any) -> str | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor.isoformat()
    return date.fromisoformat(str(valor)).isoformat()


def caducada(datos: dict[str, Any], hoy: date) -> bool:
    caduca = datos.get("caduca")
    return bool(caduca) and date.fromisoformat(caduca) < hoy


class Almacen:
    """Matrículas conocidas, ignoradas y estadísticas de detección."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store_registro: Store[dict[str, Any]] = Store(
            hass, VERSION_ALMACEN, CLAVE_REGISTRO, atomic_writes=True
        )
        self._store_detecciones: Store[dict[str, Any]] = Store(
            hass, VERSION_ALMACEN, CLAVE_DETECCIONES, atomic_writes=True
        )
        self.matriculas: dict[str, dict[str, Any]] = {}
        self.ignoradas: dict[str, dict[str, Any]] = {}
        self.vistas: dict[str, dict[str, Any]] = {}
        self.historial: list[dict[str, Any]] = []
        self.importado_de: str | None = None
        self.es_nuevo = False

    # ── Carga y guardado ──────────────────────────────────────────────

    async def async_cargar(self) -> None:
        registro = await self._store_registro.async_load()
        self.es_nuevo = registro is None
        registro = registro or {}
        self.matriculas = registro.get("matriculas", {})
        self.ignoradas = registro.get("ignoradas", {})
        self.importado_de = registro.get("importado_de")

        detecciones = await self._store_detecciones.async_load() or {}
        self.vistas = detecciones.get("vistas", {})
        self.historial = detecciones.get("historial", [])

    def _datos_registro(self) -> dict[str, Any]:
        return {
            "matriculas": self.matriculas,
            "ignoradas": self.ignoradas,
            "importado_de": self.importado_de,
        }

    def _datos_detecciones(self) -> dict[str, Any]:
        return {"vistas": self.vistas, "historial": self.historial}

    async def _async_guardar_registro(self) -> None:
        await self._store_registro.async_save(self._datos_registro())
        async_dispatcher_send(self.hass, SENAL_REGISTRO)

    async def async_volcar(self) -> None:
        """Escribe ya las detecciones pendientes (al descargar la entrada)."""
        await self._store_detecciones.async_save(self._datos_detecciones())

    # ── Consultas ─────────────────────────────────────────────────────

    def ficha(self, matricula: str) -> dict[str, Any]:
        """Datos de una matrícula registrada, con sus estadísticas."""
        return {
            "matricula": matricula,
            **self.matriculas[matricula],
            "vista": self.vistas.get(matricula),
        }

    def instantanea(self) -> dict[str, Any]:
        """Todo lo que necesita el panel (y `matriculas.listar`)."""
        matriculas = sorted(
            (self.ficha(m) for m in self.matriculas),
            key=lambda f: (f["nombre"].casefold(), f["matricula"]),
        )
        desconocidas = sorted(
            (
                {"matricula": m, **v}
                for m, v in self.vistas.items()
                if m not in self.matriculas and m not in self.ignoradas
            ),
            key=lambda v: (-v["veces"], v["matricula"]),
        )
        return {
            "matriculas": matriculas,
            "ignoradas": [{"matricula": m, **v} for m, v in sorted(self.ignoradas.items())],
            "desconocidas": desconocidas,
            "historial": self.historial[-HISTORIAL_PANEL:][::-1],
        }

    def resolver(self, leida: str) -> dict[str, Any]:
        """Identifica una lectura de Frigate.

        `abrir` se respeta también en coincidencias aproximadas: es una
        decisión expresa (ver docs/DECISIONES.md), no un descuido.
        """
        hoy = dt_util.now().date()
        vigentes = [m for m, d in self.matriculas.items() if not caducada(d, hoy)]
        c = coincidencia.buscar(leida, vigentes)
        base: dict[str, Any] = {
            "leida": c.leida,
            "metodo": c.metodo,
            "aproximada": c.aproximada,
            "candidatos": list(c.candidatos),
        }

        if c.encontrada:
            datos = self.matriculas[c.matricula]
            return {
                **base,
                "tipo": CONOCIDA,
                "conocida": True,
                "matricula": c.matricula,
                "nombre": datos["nombre"],
                "avisar": datos["avisar"],
                "abrir": datos["abrir"],
            }

        if len(vigentes) < len(self.matriculas):
            todas = coincidencia.buscar(leida, self.matriculas)
            if todas.encontrada:
                return {
                    **base,
                    "metodo": todas.metodo,
                    "aproximada": todas.aproximada,
                    "tipo": CADUCADA,
                    "conocida": False,
                    "matricula": todas.matricula,
                    "nombre": self.matriculas[todas.matricula]["nombre"],
                    "avisar": True,
                    "abrir": False,
                }

        ignorada = c.leida in self.ignoradas
        return {
            **base,
            "tipo": IGNORADA if ignorada else DESCONOCIDA,
            "conocida": False,
            "matricula": c.leida,
            "nombre": "",
            "avisar": not ignorada,
            "abrir": False,
        }

    # ── Ediciones ─────────────────────────────────────────────────────

    async def async_guardar(
        self,
        matricula: str,
        nombre: str,
        *,
        avisar: bool | None = None,
        abrir: bool | None = None,
        notas: str | None = None,
        caduca: Any = SIN_CAMBIO,
    ) -> tuple[dict[str, Any], bool]:
        """Crea o sobrescribe una matrícula. Devuelve (ficha, es_nueva)."""
        matricula = validar_matricula(matricula)
        nombre = _validar_nombre(nombre)
        ahora = dt_util.utcnow().isoformat()
        previa = self.matriculas.get(matricula)
        nueva = previa is None
        previa = previa or {}
        self.matriculas[matricula] = {
            "nombre": nombre,
            "avisar": previa.get("avisar", True) if avisar is None else bool(avisar),
            "abrir": previa.get("abrir", True) if abrir is None else bool(abrir),
            "notas": previa.get("notas", "") if notas is None else str(notas).strip(),
            "caduca": previa.get("caduca") if caduca is SIN_CAMBIO else _fecha(caduca),
            "creada": previa.get("creada", ahora),
            "modificada": ahora,
        }
        self.ignoradas.pop(matricula, None)
        await self._async_guardar_registro()
        return self.ficha(matricula), nueva

    async def async_editar(
        self,
        matricula: str,
        *,
        nueva_matricula: str | None = None,
        nombre: str | None = None,
        avisar: bool | None = None,
        abrir: bool | None = None,
        notas: str | None = None,
        caduca: Any = SIN_CAMBIO,
    ) -> dict[str, Any]:
        """Modifica una matrícula existente; solo cambia los campos indicados.

        Con `nueva_matricula` la renombra: la antigua desaparece y sus
        estadísticas pasan a la nueva (el sistema anterior dejaba las dos).
        """
        matricula = validar_matricula(matricula)
        if matricula not in self.matriculas:
            raise _error("no_existe", matricula=matricula)
        datos = dict(self.matriculas[matricula])

        destino = matricula
        if nueva_matricula is not None:
            destino = validar_matricula(nueva_matricula)
            if destino != matricula and destino in self.matriculas:
                raise _error("ya_existe", matricula=destino)

        if nombre is not None:
            datos["nombre"] = _validar_nombre(nombre)
        if avisar is not None:
            datos["avisar"] = bool(avisar)
        if abrir is not None:
            datos["abrir"] = bool(abrir)
        if notas is not None:
            datos["notas"] = str(notas).strip()
        if caduca is not SIN_CAMBIO:
            datos["caduca"] = _fecha(caduca)
        datos["modificada"] = dt_util.utcnow().isoformat()

        if destino != matricula:
            del self.matriculas[matricula]
            if matricula in self.vistas:
                self.vistas[destino] = self.vistas.pop(matricula)
                self._store_detecciones.async_delay_save(
                    self._datos_detecciones, SEGUNDOS_GUARDADO_DETECCIONES
                )
                async_dispatcher_send(self.hass, SENAL_ESTADISTICAS)
            self.ignoradas.pop(destino, None)
        self.matriculas[destino] = datos
        await self._async_guardar_registro()
        return self.ficha(destino)

    async def async_eliminar(self, matricula: str) -> None:
        matricula = validar_matricula(matricula)
        if self.matriculas.pop(matricula, None) is None:
            raise _error("no_existe", matricula=matricula)
        await self._async_guardar_registro()

    async def async_ignorar(self, matricula: str) -> None:
        """No volver a avisar de esta matrícula desconocida."""
        matricula = validar_matricula(matricula)
        if matricula in self.matriculas:
            raise _error("ignorar_registrada", matricula=matricula)
        self.ignoradas[matricula] = {"desde": dt_util.utcnow().isoformat()}
        await self._async_guardar_registro()

    async def async_dejar_de_ignorar(self, matricula: str) -> None:
        matricula = validar_matricula(matricula)
        if self.ignoradas.pop(matricula, None) is None:
            raise _error("no_ignorada", matricula=matricula)
        await self._async_guardar_registro()

    # ── Importación del sistema anterior ──────────────────────────────

    async def async_importar(self, ruta: str, *, reemplazar: bool = False) -> dict[str, int]:
        """Importa un `plates.json` del sistema anterior.

        El fichero nunca se modifica. Sin `reemplazar` se fusiona: añade las
        nuevas y actualiza nombre y aviso de las que ya existían. Con
        `reemplazar`, además borra las que no estén en el fichero. En ambos
        casos se conservan `abrir`, notas y caducidad de las que sobreviven.
        """
        try:
            contenido = await self.hass.async_add_executor_job(
                Path(ruta).read_text, "utf-8"
            )
            origen = json.loads(contenido)["plates"]
            if not isinstance(origen, dict):
                raise TypeError
        except FileNotFoundError as err:
            raise _error("importar_no_existe", ruta=ruta) from err
        except (OSError, ValueError, KeyError, TypeError) as err:
            # Un fichero ilegible aborta la importación sin tocar nada.
            raise _error("importar_ilegible", ruta=ruta) from err

        ahora = dt_util.utcnow().isoformat()
        cuenta = {"nuevas": 0, "actualizadas": 0, "sin_cambios": 0, "borradas": 0, "descartadas": 0}
        vistas_en_origen: set[str] = set()
        for clave, valor in origen.items():
            try:
                matricula = validar_matricula(clave)
                if isinstance(valor, dict):
                    nombre = _validar_nombre(valor.get("name", ""))
                    avisar = bool(valor.get("notify", True))
                else:
                    nombre, avisar = _validar_nombre(valor), True
            except ServiceValidationError:
                _LOGGER.warning("Importación: entrada descartada %r", clave)
                cuenta["descartadas"] += 1
                continue
            vistas_en_origen.add(matricula)
            previa = self.matriculas.get(matricula)
            if previa is None:
                self.matriculas[matricula] = {
                    "nombre": nombre, "avisar": avisar, "abrir": True, "notas": "",
                    "caduca": None, "creada": ahora, "modificada": ahora,
                }
                cuenta["nuevas"] += 1
            elif (previa["nombre"], previa["avisar"]) != (nombre, avisar):
                previa.update(nombre=nombre, avisar=avisar, modificada=ahora)
                cuenta["actualizadas"] += 1
            else:
                cuenta["sin_cambios"] += 1
            self.ignoradas.pop(matricula, None)

        if reemplazar:
            for matricula in set(self.matriculas) - vistas_en_origen:
                del self.matriculas[matricula]
                cuenta["borradas"] += 1

        self.importado_de = ruta
        await self._async_guardar_registro()
        _LOGGER.info("Importadas matrículas desde %s: %s", ruta, cuenta)
        return cuenta

    # ── Detecciones ───────────────────────────────────────────────────

    @callback
    def anotar_deteccion(self, entrada: dict[str, Any]) -> None:
        """Suma una detección ya cerrada a las estadísticas y al historial."""
        clave = entrada["matricula"]
        cuando = entrada["hora"]
        vista = self.vistas.setdefault(clave, {"primera": cuando, "veces": 0})
        vista["ultima"] = cuando
        vista["veces"] += 1
        vista["camara"] = entrada.get("camara", "")
        # Para la foto de la última vez en el panel.
        vista["frigate_id"] = entrada.get("frigate_id", "")
        vista["leida"] = entrada.get("leida", clave)
        self.historial.append(entrada)
        del self.historial[:-MAX_HISTORIAL]
        self._store_detecciones.async_delay_save(
            self._datos_detecciones, SEGUNDOS_GUARDADO_DETECCIONES
        )
        async_dispatcher_send(self.hass, SENAL_ESTADISTICAS)
