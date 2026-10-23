"""Formato de números y textos en estilo venezolano (1.234,56)."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date


def es_numero(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def num(x, dec: int = 2) -> str:
    if not es_numero(x):
        return "—"
    s = f"{x:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def cant(x) -> str:
    if not es_numero(x):
        return "—"
    return num(x, 0) if float(x).is_integer() else num(x, 2)


def pct(x, dec: int = 1) -> str:
    if not es_numero(x):
        return "—"
    signo = "+" if x > 0 else ""
    return f"{signo}{num(x * 100, dec)}%"


def fecha(d) -> str:
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    if not d:
        return "—"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(d))
    return f"{m[3]}/{m[2]}/{m[1]}" if m else str(d)


def normalizar(texto) -> str:
    """Clave de comparación: sin acentos, mayúsculas, espacios simples.

    Se usa para enlazar descripciones entre la lista de precios, el historial y
    lo que se escribe a mano.
    """
    if texto is None or (isinstance(texto, float) and math.isnan(texto)):
        return ""
    t = unicodedata.normalize("NFD", str(texto))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().upper()


def slug(texto: str, largo: int = 40) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", normalizar(texto)).strip("_")[:largo] or "archivo"
