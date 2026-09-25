"""Constantes de la integración Matrículas."""

from __future__ import annotations

DOMAIN = "matriculas"

CONF_PREFIJO_MQTT = "prefijo_mqtt"
CONF_CAMARAS = "camaras"

DEFECTO_PREFIJO_MQTT = "frigate"

# Fichero del sistema anterior (paquete YAML + scripts Python). Se importa una
# sola vez, la primera vez que arranca la integración, y nunca se modifica.
RUTA_LEGADO = "packages/videoportero/plates.json"

# Dos ficheros a propósito: el registro solo se escribe cuando alguien edita
# una matrícula; las detecciones se escriben a menudo. Así un fallo de
# escritura por detecciones nunca puede tocar el registro.
CLAVE_REGISTRO = "matriculas.registro"
CLAVE_DETECCIONES = "matriculas.detecciones"
VERSION_ALMACEN = 1

MAX_HISTORIAL = 500
SEGUNDOS_GUARDADO_DETECCIONES = 60

# Frigate manda varias lecturas del mismo coche (mismo id de objeto) mientras
# lo sigue. Pasado este tiempo sin lecturas nuevas, se da por cerrado y se
# anota en las estadísticas con la mejor identificación conseguida.
SEGUNDOS_CIERRE_OBJETO = 30

LONGITUD_MINIMA = 2
LONGITUD_MAXIMA = 10
LONGITUD_MAXIMA_NOMBRE = 100

EVENTO_DETECTADA = "matriculas_detectada"
# Una matrícula parece mal guardada (ver sugerencias.py). Una vez por sugerencia.
EVENTO_SUGERENCIA = "matriculas_sugerencia"

SENAL_REGISTRO = f"{DOMAIN}_registro_actualizado"
SENAL_DETECCION = f"{DOMAIN}_deteccion"
SENAL_ESTADISTICAS = f"{DOMAIN}_estadisticas_actualizadas"

# Panel de la barra lateral
URL_PANEL = "matriculas"
RUTA_ESTATICA = "/matriculas_static"
FICHERO_PANEL = "matriculas-panel.js"
ELEMENTO_PANEL = "matriculas-panel"
# El historial completo se guarda (MAX_HISTORIAL); al panel solo van los últimos.
HISTORIAL_PANEL = 100

CONOCIDA = "conocida"
DESCONOCIDA = "desconocida"
IGNORADA = "ignorada"
CADUCADA = "caducada"
TIPOS_DETECCION = [CONOCIDA, DESCONOCIDA, IGNORADA, CADUCADA]
