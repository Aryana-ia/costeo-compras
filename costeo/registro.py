"""Guardar un costeo: alimenta el historial de compras y el archivo de costeos.

Cada vez que se guarda un costeo pasan dos cosas:

1. **Historial de compras** (``historial.csv``): una fila por producto con fecha,
   proveedor, precio por pieza sin IVA (con descuentos), costo por kilo en $ interno,
   cantidad, condiciones, tasa, factura / OC y observación. Es lo que la app usa
   para mostrar la «última compra» y el «último precio de cada proveedor».
2. **Costeos** (``costeos.csv``): el detalle completo de cada producto, con todas
   las columnas del resultado (costo, +17 %, +18 %, P3, diferencias, acción…),
   para consultar o descargar después.

Las filas de un mismo costeo llevan el mismo identificador (columna ``COSTEO``).
Si se vuelve a guardar el mismo costeo, sus filas se reemplazan: no se duplican.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from . import formato as fmt
from .calculo import describir_iva, describir_pago
from .exportar import tabla
from .historial import COLUMNAS as COLUMNAS_HISTORIAL
from .modelos import Condiciones, Parametros, Proveedor, Resultado


def nuevo_id(prov: Proveedor, p: Parametros, ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now()
    return f"{p.fecha.isoformat()}_{fmt.slug(prov.nombre, 20)}_{ahora.strftime('%H%M%S')}"


def _descuento_total(cond: Condiciones, extra: float) -> float:
    """Descuento equivalente de la cascada (3 % y 2 % → 4,94 %)."""
    f = 1.0
    for d in [*cond.descuentos, extra or 0]:
        f *= 1 - d / 100
    return round((1 - f) * 100, 4)


def filas_historial(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones,
                    costeo_id: str, factura: str = "", observacion: str = "") -> pd.DataFrame:
    """Una fila por producto costeado (se omiten los que tienen error o no tienen cantidad)."""
    mon = "Bs" if cond.moneda == "bs" else "$"
    condiciones = f"{describir_pago(cond)} · {describir_iva(cond, p.iva)}"
    filas = []
    for r in res.lineas:
        if not r.tiene_costo or not fmt.es_numero(r.linea.cantidad) or r.linea.cantidad <= 0:
            continue
        filas.append({
            "FECHA": p.fecha.isoformat(),
            "PROVEEDOR": prov.nombre,
            "DESCRIPCION": r.linea.descripcion,
            "PRECIO": round(r.pieza_sin_iva, 4),
            "COSTO_KG": round(r.costo_kg, 4),
            "CANTIDAD": r.linea.cantidad,
            "MONEDA": mon,
            "FACTURA": factura.strip(),
            "RIF": "",
            "CONTACTO": "",
            "CONDICIONES": condiciones,
            "DESCUENTO": _descuento_total(cond, r.linea.desc_extra),
            "OBSERVACION": observacion.strip(),
            "TASA": p.tasa_bcv,
            "COSTEO": costeo_id,
        })
    return pd.DataFrame(filas, columns=COLUMNAS_HISTORIAL)


def filas_costeo(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones,
                 costeo_id: str, factura: str = "", observacion: str = "") -> pd.DataFrame:
    """Detalle completo del costeo (todas las columnas del resultado) más los datos de cabecera."""
    df = tabla(res, p, prov, cond)
    cabecera = {
        "COSTEO": costeo_id,
        "Guardado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Fecha pedido": p.fecha.isoformat(),
        "Proveedor": prov.nombre,
        "Tasa BCV": p.tasa_bcv,
        "Tasa interna": p.tasa_interna,
        "Forma de pago": describir_pago(cond),
        "IVA": describir_iva(cond, p.iva),
        "Descuentos %": " + ".join(f"{d:g}" for d in cond.descuentos),
        "Flete": cond.flete,
        "Moneda flete": cond.flete_moneda,
        "Factura / OC": factura.strip(),
        "Nota del costeo": observacion.strip(),
    }
    for k, (col, val) in enumerate(cabecera.items()):
        df.insert(k, col, val)
    return df


def reemplazar(existente: pd.DataFrame | None, nuevas: pd.DataFrame, costeo_id: str) -> pd.DataFrame:
    """Quita las filas anteriores de ese costeo y agrega las nuevas al final."""
    if existente is None or existente.empty:
        return nuevas.reset_index(drop=True)
    base = existente.drop(columns=[c for c in ("CLAVE",) if c in existente.columns])
    if "COSTEO" in base.columns:
        base = base[base["COSTEO"].fillna("").astype(str) != costeo_id]
    return pd.concat([base, nuevas], ignore_index=True)


def resumen_costeos(costeos: pd.DataFrame | None) -> pd.DataFrame:
    """Una fila por costeo guardado, del más reciente al más antiguo."""
    if costeos is None or costeos.empty:
        return pd.DataFrame(columns=["COSTEO", "Guardado", "Fecha pedido", "Proveedor", "Productos", "Subir", "Factura / OC"])
    g = costeos.groupby("COSTEO", sort=False)
    out = g.agg(**{
        "Guardado": ("Guardado", "first"),
        "Fecha pedido": ("Fecha pedido", "first"),
        "Proveedor": ("Proveedor", "first"),
        "Productos": ("Producto", "count"),
        "Subir": ("Acción", lambda s: int((s == "SUBIR").sum())),
        "Factura / OC": ("Factura / OC", "first"),
    }).reset_index()
    return out.sort_values("Guardado", ascending=False).reset_index(drop=True)
