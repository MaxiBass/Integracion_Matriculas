"""Detección de matrículas probablemente mal guardadas.

Si la primera lectura de un coche era errónea y se guardó así, la tolerancia
a errores lo sigue reconociendo, pero la matrícula queda mal para siempre.
Dos señales, calibradas con dos meses de lecturas reales (357 visitas, ver
docs/DECISIONES.md §10):

- Frigate lee mal una matrícula registrada en ~1 % de las visitas y sus
  errores no se repiten: cada lectura errónea apareció una sola vez. Si una
  registrada se lee una y otra vez como OTRA matrícula concreta, y más veces
  que como la guardada, lo que está mal es la guardada (CORRECCION).
- Dos registradas que se diferencian en un solo carácter suelen ser el mismo
  coche guardado dos veces, una con la lectura errónea (DUPLICADO). Además,
  una lectura dudosa entre las dos no reconoce ninguna, por ambigua.

Solo se sugiere; nunca se corrige solo. La misma señal aparece si un coche
distinto, con una matrícula a un carácter de una registrada, pasa a menudo:
la tolerancia lo toma por el registrado, y corregir en silencio le daría su
identidad y su permiso de apertura.

No importa nada de Home Assistant.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

CORRECCION = "correccion"
DUPLICADO = "duplicado"

# Veces (visitas distintas) que tiene que repetirse la misma lectura distinta.
MIN_REPETICIONES = 2
# Lecturas distintas que se recuerdan por matrícula (las más frecuentes).
MAX_LECTURAS = 8


def diferencias(a: str, b: str) -> int:
    if len(a) != len(b):
        return 99
    return sum(x != y for x, y in zip(a, b))


def id_sugerencia(tipo: str, a: str, b: str) -> str:
    return f"{tipo}_{a}_{b}".lower()


def anotar_lectura(lecturas: dict[str, int], leida: str) -> None:
    """Suma una visita a las lecturas de una matrícula, sin dejarlas crecer."""
    lecturas[leida] = lecturas.get(leida, 0) + 1
    exceso = len(lecturas) - MAX_LECTURAS
    if exceso > 0:
        # Fuera las menos vistas, pero nunca la que se acaba de anotar.
        candidatas = sorted((k for k in lecturas if k != leida), key=lambda k: (lecturas[k], k))
        for clave in candidatas[:exceso]:
            del lecturas[clave]


def lecturas_de(vistas: dict[str, dict[str, Any]], matricula: str) -> dict[str, int]:
    return (vistas.get(matricula) or {}).get("lecturas") or {}


def correccion(
    matricula: str,
    datos: dict[str, Any],
    vistas: dict[str, dict[str, Any]],
    registradas: set[str],
) -> dict[str, Any] | None:
    lecturas = lecturas_de(vistas, matricula)
    propias = lecturas.get(matricula, 0)
    candidatas = [
        (veces, leida)
        for leida, veces in lecturas.items()
        if leida != matricula
        and leida not in registradas
        and veces >= MIN_REPETICIONES
        and veces > propias
    ]
    if not candidatas:
        return None
    veces, propuesta = max(candidatas)
    return {
        "id": id_sugerencia(CORRECCION, matricula, propuesta),
        "tipo": CORRECCION,
        "matricula": matricula,
        "propuesta": propuesta,
        "nombre": datos.get("nombre", ""),
        "veces_propuesta": veces,
        "veces_guardada": propias,
    }


def calcular(
    matriculas: dict[str, dict[str, Any]],
    vistas: dict[str, dict[str, Any]],
    descartadas: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """Todas las sugerencias vigentes, por id."""
    descartadas = set(descartadas)
    registradas = set(matriculas)
    salida: dict[str, dict[str, Any]] = {}

    for matricula, datos in matriculas.items():
        s = correccion(matricula, datos, vistas, registradas)
        if s and s["id"] not in descartadas:
            salida[s["id"]] = s

    orden = sorted(registradas)
    for i, a in enumerate(orden):
        for b in orden[i + 1 :]:
            if diferencias(a, b) != 1:
                continue
            ident = id_sugerencia(DUPLICADO, a, b)
            if ident in descartadas:
                continue
            va = lecturas_de(vistas, a).get(a, 0)
            vb = lecturas_de(vistas, b).get(b, 0)
            sobra = a if va == 0 and vb > 0 else b if vb == 0 and va > 0 else ""
            salida[ident] = {
                "id": ident,
                "tipo": DUPLICADO,
                "matricula": a,
                "otra": b,
                "nombre": matriculas[a].get("nombre", ""),
                "nombre_otra": matriculas[b].get("nombre", ""),
                "veces": va,
                "veces_otra": vb,
                "sobra": sobra,
            }
    return salida
