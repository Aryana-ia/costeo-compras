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


def leer_html_bcv(html: str) -> TasaBCV:
    """Extrae la tasa del dólar y la fecha valor del HTML de bcv.org.ve."""
    m = re.search(r'id="dolar".*?<strong>\s*([\d.,]+)\s*</strong>', html, re.S)
    if not m:
        raise ErrorDeDatos("La página del BCV no trae el bloque del dólar (puede haber cambiado su diseño).")
    valor = _num(m[1])
    f = re.search(r'class="date-display-single"[^>]*content="(\d{4}-\d{2}-\d{2})', html)
    if not valor > 0:
        raise ErrorDeDatos(f"No se pudo leer el número de la tasa BCV ({m[1]!r}).")
    return TasaBCV(valor, date.fromisoformat(f[1]) if f else None, "bcv.org.ve")


def _desde_bcv() -> TasaBCV:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # aviso de certificado no verificado
        r = requests.get(URL_BCV, timeout=TIMEOUT, verify=False, headers=CABECERAS)
    r.raise_for_status()
    return leer_html_bcv(r.text)


def _desde_respaldo() -> TasaBCV:
    r = requests.get(URL_RESPALDO, timeout=TIMEOUT, headers=CABECERAS)
    r.raise_for_status()
    d = r.json()
    valor = _num(d.get("promedio"))
    if not valor > 0:
        raise ErrorDeDatos("El servicio de respaldo no trajo la tasa.")
    fecha = str(d.get("fechaActualizacion") or "")[:10]
    return TasaBCV(valor, date.fromisoformat(fecha) if re.match(r"\d{4}-\d{2}-\d{2}$", fecha) else None, "ve.dolarapi.com")


def obtener_tasa_bcv() -> TasaBCV:
    """Intenta el BCV y, si falla, el respaldo. Lanza ErrorDeDatos con ambos motivos."""
    errores = []
    for nombre, fuente in (("BCV", _desde_bcv), ("respaldo", _desde_respaldo)):
        try:
            return fuente()
        except requests.RequestException:
            errores.append(f"{nombre} sin respuesta")
        except (ValueError, ErrorDeDatos) as e:
            errores.append(f"{nombre}: {e}")
    raise ErrorDeDatos("No se pudo traer la tasa BCV automáticamente. Escríbela a mano. (" + " · ".join(errores) + ")")
