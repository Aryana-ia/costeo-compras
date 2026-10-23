"""Historial de compras: lectura del Excel y consulta por producto.

Columnas obligatorias: FECHA, PROVEEDOR, DESCRIPCION, PRECIO.
Opcionales: COSTO KG, CANTIDAD, MONEDA, FACTURA / OC, RIF, CONTACTO,
CONDICIONES DE PAGO, DESCUENTO %, OBSERVACION, TASA.

El historial se enlaza con los productos por descripción normalizada
(sin acentos ni mayúsculas), así que debe escribirse igual que en la lista de precios.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from .catalogo import buscar_encabezado, leer_hoja
from .formato import normalizar
from .modelos import ErrorDeDatos, _num

COLUMNAS = [
    "FECHA", "PROVEEDOR", "DESCRIPCION", "PRECIO", "COSTO_KG", "CANTIDAD", "MONEDA",
    "FACTURA", "RIF", "CONTACTO", "CONDICIONES", "DESCUENTO", "OBSERVACION", "TASA",
]
PLANTILLA = [
    "FECHA", "PROVEEDOR", "DESCRIPCION", "PRECIO UNITARIO", "COSTO KG", "CANTIDAD", "MONEDA",
    "FACTURA / OC", "RIF", "CONTACTO", "CONDICIONES DE PAGO", "DESCUENTO %", "OBSERVACION", "TASA",
]


def a_fecha_iso(v) -> str:
    """Convierte fechas de Excel (datetime, serial o texto dd/mm/aaaa) a 'aaaa-mm-dd'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))).strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", s)
    if m:
        y = m[3] if len(m[3]) == 4 else "20" + m[3]
        return f"{y}-{int(m[2]):02d}-{int(m[1]):02d}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    return m[0] if m else ""


@dataclass
class LecturaHistorial:
    archivo: str
    hoja: str
    datos: pd.DataFrame
    filas_omitidas: list[int] = field(default_factory=list)
    opcionales_faltantes: list[str] = field(default_factory=list)


def leer_historial(archivo) -> LecturaHistorial:
    hoja, crudo = leer_hoja(archivo, preferida="HISTORIAL")
    enc = buscar_encabezado(crudo, lambda h: any("PROVEEDOR" in x for x in h))
    if not enc:
        raise ErrorDeDatos("No encontré la columna PROVEEDOR. Usa la plantilla como guía.")
    i, h = enc

    def col(patron, excluir=None):
        return next((k for k, x in enumerate(h) if re.search(patron, x) and not (excluir and re.search(excluir, x))), -1)

    c = {
        "FECHA": col(r"FECHA"),
        "PROVEEDOR": col(r"PROVEEDOR", r"RIF"),
        "DESCRIPCION": next((k for k in (col(r"^DESCRIPCION UNICA"), col(r"^DESCRIPCION|^PRODUCTO|ARTICULO")) if k >= 0), -1),
        "PRECIO": next((k for k in (col(r"PRECIO", r"KG|KILO"), col(r"COSTO", r"KG|KILO")) if k >= 0), -1),
        "COSTO_KG": col(r"(COSTO|PRECIO).*(KG|KILO)"),
        "CANTIDAD": col(r"CANT"),
        "MONEDA": col(r"MONEDA"),
        "FACTURA": col(r"FACTURA|DOCUMENTO|ORDEN|^N.? ?OC|^OC"),
        "RIF": col(r"RIF"),
        "CONTACTO": col(r"CONTACTO|TELEFONO|TLF|CORREO|EMAIL"),
        "CONDICIONES": col(r"CONDICION|FORMA DE PAGO|CREDITO"),
        "DESCUENTO": col(r"DESCUENTO"),
        "OBSERVACION": col(r"OBSERV|NOTA"),
        "TASA": col(r"TASA"),
    }
    faltan = [k for k in ("FECHA", "PROVEEDOR", "DESCRIPCION", "PRECIO") if c[k] < 0]
    if faltan:
        raise ErrorDeDatos(
            "Faltan columnas obligatorias: " + ", ".join(faltan)
            + ". Columnas encontradas: " + ", ".join(x for x in h if x)
        )
    numericas = {"PRECIO", "COSTO_KG", "CANTIDAD", "DESCUENTO", "TASA"}
    filas, omitidas = [], []
    for n, fila in enumerate(crudo.iloc[i + 1:].itertuples(index=False), start=i + 2):
        fila = list(fila)
        if all(v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" for v in fila):
            continue
        reg = {}
        for k in COLUMNAS:
            v = fila[c[k]] if c[k] >= 0 else None
            if k == "FECHA":
                reg[k] = a_fecha_iso(v)
            elif k in numericas:
                reg[k] = _num(v, float("nan"))
            else:
                reg[k] = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
        if not reg["FECHA"] or not reg["PROVEEDOR"] or not reg["DESCRIPCION"] or not reg["PRECIO"] > 0:
            omitidas.append(n)
            continue
        filas.append(reg)
    df = pd.DataFrame(filas, columns=COLUMNAS)
    df["CLAVE"] = df["DESCRIPCION"].map(normalizar)
    opcionales = [k for k in ("COSTO_KG", "CANTIDAD", "MONEDA", "FACTURA", "RIF", "CONTACTO", "CONDICIONES", "TASA") if c[k] < 0]
    return LecturaHistorial(getattr(archivo, "name", str(archivo)), hoja, df, omitidas, opcionales)


class Historial:
    """Índice en memoria para consultar compras por producto."""

    def __init__(self, df: pd.DataFrame | None):
        if df is None or df.empty:
            self.df = pd.DataFrame(columns=COLUMNAS + ["CLAVE"])
        else:
            self.df = df.copy()
            if "CLAVE" not in self.df:
                self.df["CLAVE"] = self.df["DESCRIPCION"].map(normalizar)
        self.df = self.df.sort_values("FECHA", ascending=False, kind="stable")
        self._por_clave = {k: g for k, g in self.df.groupby("CLAVE", sort=False)}

    def compras(self, descripcion: str) -> pd.DataFrame:
        return self._por_clave.get(normalizar(descripcion), self.df.iloc[0:0])

    def ultima(self, descripcion: str) -> dict | None:
        g = self.compras(descripcion)
        return None if g.empty else g.iloc[0].to_dict()

    def por_proveedor(self, descripcion: str) -> pd.DataFrame:
        """Última compra de cada proveedor que vendió el producto."""
        g = self.compras(descripcion)
        if g.empty:
            return g
        return g.assign(_p=g["PROVEEDOR"].map(normalizar)).drop_duplicates("_p").drop(columns="_p")


def plantilla_excel() -> bytes:
    ejemplo = ["18/09/2026", "UNICOM", 'CABILLA 1/2" X 12 MTS', 10.52, 0.8818, 600, "$", "F-0012",
               "J-00000000-0", "0414-0000000", "50% $ / 50% Bs BCV", 0, "Fila de ejemplo: bórrala", 198.4]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        pd.DataFrame([ejemplo], columns=PLANTILLA).to_excel(w, index=False, sheet_name="HISTORIAL")
        hoja = w.sheets["HISTORIAL"]
        for k, nombre in enumerate(PLANTILLA):
            hoja.set_column(k, k, 42 if nombre == "DESCRIPCION" else 16)
    return buf.getvalue()


def ejemplo() -> pd.DataFrame:
    filas = [
        ["2026-09-18", "UNICOM", 'CABILLA 1/2" X 12 MTS', 10.52, 0.8818, 600, "$", "F-0012", "", "", "50% $ / 50% Bs BCV", 0, "Ejemplo", 198.4],
        ["2026-08-02", "COMPLEJO", 'CABILLA 1/2" X 12 MTS', 10.95, 0.9179, 400, "$", "F-7741", "", "", "Monto en $ + Bs BCV", 0, "Ejemplo", 181.2],
        ["2026-09-18", "UNICOM", 'CABILLA 3/8" X 12 MTS', 6.05, 0.9003, 900, "$", "F-0012", "", "", "50% $ / 50% Bs BCV", 0, "Ejemplo", 198.4],
    ]
    df = pd.DataFrame(filas, columns=COLUMNAS)
    df["CLAVE"] = df["DESCRIPCION"].map(normalizar)
    return df
