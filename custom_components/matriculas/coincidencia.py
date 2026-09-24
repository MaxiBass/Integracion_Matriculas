"""Búsqueda de matrículas con tolerancia a errores de lectura (OCR).

Es un porte fiel de la macro `buscar_matricula` de
`custom_templates/matriculas.jinja`, con una diferencia a propósito: el paso
3b funciona. En la macro, la lista de candidatos de ese paso se reasignaba
dentro de un `for` sin `namespace`, y en Jinja esa asignación no sobrevive al
bucle, así que el paso nunca encontraba nada.

No importa nada de Home Assistant, para poder probarlo con `python3` a secas.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Formato español actual: 4 cifras y 3 consonantes (sin vocales, Ñ ni Q).
FORMATO_ESPANOL = re.compile(r"^[0-9]{4}[BCDFGHJKLMNPRSTVWXYZ]{3}$")

_NO_ALFANUMERICO = re.compile(r"[^0-9A-Z]")

# Paso 1: corrección posicional para matrículas de 7 caracteres (NNNNLLL).
# En la parte numérica una letra se toma por la cifra a la que se parece, y
# en la parte de letras al revés.
A_DIGITO = {
    "O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
    "Z": "2", "S": "5", "G": "6", "B": "8", "T": "7",
}
A_LETRA = {"0": "D", "1": "L", "2": "Z", "5": "S", "6": "G", "8": "B", "7": "T"}

# Paso 3a: confusiones típicas del OCR entre caracteres del mismo tipo.
# Clave: carácter leído. Valor: caracteres reales con los que se confunde.
CONFUSIONES = {
    "0": "8", "8": "0", "1": "7", "7": "1", "5": "6", "6": "5",
    "V": "YW", "Y": "VT", "W": "V", "T": "Y",
    "B": "R", "R": "B", "C": "G", "G": "C",
    "F": "P", "P": "F", "M": "N", "N": "M",
}

EXACTA = "exacta"
NORMALIZADA = "normalizada"
CONFUSION = "confusion"
UN_CARACTER = "un_caracter"


@dataclass(frozen=True, slots=True)
class Coincidencia:
    """Resultado de buscar una lectura entre las matrículas conocidas."""

    leida: str
    matricula: str = ""
    metodo: str = ""
    # Si la tolerancia encuentra más de un candidato no se elige ninguno:
    # quedan aquí para diagnóstico.
    candidatos: tuple[str, ...] = ()

    @property
    def encontrada(self) -> bool:
        return bool(self.matricula)

    @property
    def aproximada(self) -> bool:
        return self.metodo in (CONFUSION, UN_CARACTER)


def normalizar(texto: str) -> str:
    """Deja solo cifras y letras, en mayúsculas: ' 1234-bcd' → '1234BCD'."""
    return _NO_ALFANUMERICO.sub("", str(texto).upper())


def es_formato_espanol(matricula: str) -> bool:
    return bool(FORMATO_ESPANOL.match(matricula))


def normalizar_posicional(matricula: str) -> str:
    if len(matricula) != 7:
        return matricula
    return "".join(
        A_DIGITO.get(c, c) if i < 4 else A_LETRA.get(c, c)
        for i, c in enumerate(matricula)
    )


def _diferencias_tipadas(leida: str, conocida: str) -> int | None:
    """Posiciones distintas si todas son confusiones típicas; si no, None."""
    n = 0
    for a, b in zip(leida, conocida):
        if a != b:
            if b not in CONFUSIONES.get(a, ""):
                return None
            n += 1
    return n


def _diferencias(leida: str, conocida: str) -> int:
    return sum(a != b for a, b in zip(leida, conocida))


def buscar(leida: str, conocidas: Iterable[str]) -> Coincidencia:
    """Busca una lectura entre las matrículas conocidas.

    1. Corrección posicional (solo afecta a lecturas de 7 caracteres).
    2. Coincidencia exacta con la lectura o con su versión corregida.
    3a. Una sola confusión típica de OCR, si hay un único candidato.
    3b. Si 3a no encuentra ninguno: un carácter distinto cualquiera, si hay
        un único candidato.

    Con más de un candidato en 3a no se prueba 3b: la ambigüedad ya dice que
    la lectura no es fiable.
    """
    placa = normalizar(leida)
    if not placa:
        return Coincidencia(leida="")
    conocidas = set(conocidas)
    if placa in conocidas:
        return Coincidencia(placa, placa, EXACTA)
    norm = normalizar_posicional(placa)
    if norm in conocidas:
        return Coincidencia(placa, norm, NORMALIZADA)

    misma_longitud = sorted(k for k in conocidas if len(k) == len(norm))
    tipadas = [k for k in misma_longitud if _diferencias_tipadas(norm, k) == 1]
    if len(tipadas) == 1:
        return Coincidencia(placa, tipadas[0], CONFUSION)
    if tipadas:
        return Coincidencia(placa, candidatos=tuple(tipadas))

    genericas = [k for k in misma_longitud if _diferencias(norm, k) == 1]
    if len(genericas) == 1:
        return Coincidencia(placa, genericas[0], UN_CARACTER)
    return Coincidencia(placa, candidatos=tuple(genericas))
