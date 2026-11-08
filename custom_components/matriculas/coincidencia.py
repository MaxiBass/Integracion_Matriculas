"""Búsqueda de matrículas con tolerancia a errores de lectura (OCR).

Nació como porte fiel de la macro `buscar_matricula` de
`custom_templates/matriculas.jinja` (retirada de casa: ya no existe), con
estas diferencias a propósito (DECISIONES §3):

- El paso 3b funciona. En la macro, la lista de candidatos de ese paso se
  reasignaba dentro de un `for` sin `namespace`, y en Jinja esa asignación no
  sobrevive al bucle, así que el paso nunca encontraba nada.
- (v0.3.3) Los pasos 3a y 3b comparan la lectura tal cual y la corregida
  (paso 1) y se quedan con la menor diferencia: la corrección posicional
  supone el formato actual (NNNNLLL) y estropeaba las matrículas provinciales
  antiguas (`B1234XY` leída `B1234XV` pasaba a `81234XV`).
- (v0.3.3) Los pasos 3a y 3b solo se aplican a lecturas de 6 caracteres o
  más: en una matrícula corta, un carácter distinto es casi toda la matrícula
  y una coincidencia aproximada abre la puerta.

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

# Longitud mínima de una lectura para buscarle una coincidencia aproximada
# (pasos 3a y 3b). Las matrículas más cortas solo coinciden exactas.
LONGITUD_MINIMA_APROXIMADA = 6

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

    3a y 3b solo con lecturas de `LONGITUD_MINIMA_APROXIMADA` caracteres o
    más, y comparando tanto la lectura como su versión corregida (la que
    menos se diferencie).

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

    if len(placa) < LONGITUD_MINIMA_APROXIMADA:
        return Coincidencia(placa)

    variantes = (placa,) if norm == placa else (placa, norm)
    misma_longitud = sorted(k for k in conocidas if len(k) == len(placa))
    tipadas = [
        k for k in misma_longitud if any(_diferencias_tipadas(v, k) == 1 for v in variantes)
    ]
    if len(tipadas) == 1:
        return Coincidencia(placa, tipadas[0], CONFUSION)
    if tipadas:
        return Coincidencia(placa, candidatos=tuple(tipadas))

    genericas = [k for k in misma_longitud if min(_diferencias(v, k) for v in variantes) == 1]
    if len(genericas) == 1:
        return Coincidencia(placa, genericas[0], UN_CARACTER)
    return Coincidencia(placa, candidatos=tuple(genericas))
