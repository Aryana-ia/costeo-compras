"""Tasa oficial del dólar publicada por el BCV.

Fuentes, en orden:

1. **bcv.org.ve** (página oficial): el valor está en ``<div id="dolar"> … <strong>210,50</strong>``
   y la fecha en ``<span class="date-display-single" content="2026-10-24T00:00:00-04:00">``.
   El sitio del BCV suele tener el certificado SSL incompleto, por eso la consulta
   se hace sin verificarlo (solo se lee un número público, no se envía nada).
2. **ve.dolarapi.com** (respaldo): ``/v1/dolares/oficial`` → ``{"promedio": 210.5, "fechaActualizacion": "..."}``.

Importante: el BCV publica la tasa con una **fecha valor** (normalmente el siguiente
día hábil). La app la muestra para que coincida con la fecha del pedido.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from datetime import date

import requests

from .modelos import ErrorDeDatos, _num

URL_BCV = "https://www.bcv.org.ve/"
URL_RESPALDO = "https://ve.dolarapi.com/v1/dolares/oficial"
TIMEOUT = 12
CABECERAS = {"User-Agent": "Mozilla/5.0 (CosteoComprasACEVAL)"}


@dataclass
class TasaBCV:
    valor: float
    fecha_valor: date | None
    fuente: str


BLOQUES = {"usd": ("dolar", "dólar"), "eur": ("euro", "euro")}
URLS_RESPALDO = {"usd": URL_RESPALDO, "eur": "https://ve.dolarapi.com/v1/euros/oficial"}


def leer_html_bcv(html: str, moneda: str = "usd") -> TasaBCV:
    """Extrae la tasa (dólar o euro) y la fecha valor del HTML de bcv.org.ve."""
    bloque, nombre = BLOQUES[moneda]
    m = re.search(rf'id="{bloque}".*?<strong>\s*([\d.,]+)\s*</strong>', html, re.S)
    if not m:
        raise ErrorDeDatos(f"La página del BCV no trae el bloque del {nombre} (puede haber cambiado su diseño).")
    valor = _num(m[1])
    f = re.search(r'class="date-display-single"[^>]*content="(\d{4}-\d{2}-\d{2})', html)
    if not valor > 0:
        raise ErrorDeDatos(f"No se pudo leer el número de la tasa BCV del {nombre} ({m[1]!r}).")
    return TasaBCV(valor, date.fromisoformat(f[1]) if f else None, "bcv.org.ve")


def _html_bcv() -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # aviso de certificado no verificado
        r = requests.get(URL_BCV, timeout=TIMEOUT, verify=False, headers=CABECERAS)
    r.raise_for_status()
    return r.text


def _desde_bcv(moneda: str = "usd") -> TasaBCV:
    return leer_html_bcv(_html_bcv(), moneda)


def _desde_respaldo(moneda: str = "usd") -> TasaBCV:
    r = requests.get(URLS_RESPALDO[moneda], timeout=TIMEOUT, headers=CABECERAS)
    r.raise_for_status()
    d = r.json()
    valor = _num(d.get("promedio"))
    if not valor > 0:
        raise ErrorDeDatos("El servicio de respaldo no trajo la tasa.")
    fecha = str(d.get("fechaActualizacion") or "")[:10]
    return TasaBCV(valor, date.fromisoformat(fecha) if re.match(r"\d{4}-\d{2}-\d{2}$", fecha) else None, "ve.dolarapi.com")


def obtener_tasa_bcv(moneda: str = "usd") -> TasaBCV:
    """Intenta el BCV y, si falla, el respaldo. Lanza ErrorDeDatos con ambos motivos."""
    nombre_m = "$" if moneda == "usd" else "€"
    errores = []
    for nombre, fuente in (("BCV", _desde_bcv), ("respaldo", _desde_respaldo)):
        try:
            return fuente(moneda)
        except requests.RequestException:
            errores.append(f"{nombre} sin respuesta")
        except (ValueError, ErrorDeDatos) as e:
            errores.append(f"{nombre}: {e}")
    raise ErrorDeDatos(f"No se pudo traer la tasa BCV {nombre_m} automáticamente. Escríbela a mano. (" + " · ".join(errores) + ")")


def obtener_tasas_bcv() -> dict:
    """Dólar y euro del BCV con una sola consulta a la página (respaldo por separado si falla).

    Devuelve {"usd": TasaBCV | ErrorDeDatos, "eur": TasaBCV | ErrorDeDatos}.
    """
    salida = {}
    try:
        html = _html_bcv()
    except requests.RequestException:
        html = None
    for moneda in ("usd", "eur"):
        try:
            salida[moneda] = leer_html_bcv(html, moneda) if html else obtener_tasa_bcv(moneda)
        except ErrorDeDatos:
            try:
                salida[moneda] = obtener_tasa_bcv(moneda)
            except ErrorDeDatos as e:
                salida[moneda] = e
    return salida
