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

import json
import math
import re
from dataclasses import asdict
from datetime import date, datetime

import pandas as pd

from . import formato as fmt
from .calculo import describir_iva, describir_pago
from .exportar import tabla
from .historial import COLUMNAS as COLUMNAS_HISTORIAL
from .modelos import Condiciones, Linea, Parametros, Proveedor, Resultado, _num


def nuevo_id(prov: Proveedor, p: Parametros, ahora: datetime | None = None) -> str:
    ahora = ahora or fmt.ahora()
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
        "Guardado": fmt.ahora().strftime("%Y-%m-%d %H:%M"),
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
        # Todo lo necesario para reabrir el costeo tal cual (tasas, condiciones y productos)
        "Estado": estado_json(res, p, prov, cond),
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


# ---------------------------------------------------------------------------
# Reabrir un costeo guardado
# ---------------------------------------------------------------------------
def _limpio(v):
    return None if isinstance(v, float) and math.isnan(v) else v


def estado_json(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones) -> str:
    datos = {
        "version": 1,
        "parametros": {**asdict(p), "fecha": p.fecha.isoformat()},
        "proveedor": {"id": prov.id, "nombre": prov.nombre},
        "condiciones": cond.a_dict(),
        "lineas": [{k: _limpio(v) for k, v in asdict(r.linea).items()} for r in res.lineas],
    }
    return json.dumps(datos, ensure_ascii=False)


def _nan(v):
    return float("nan") if v is None else v


def _desde_estado(texto: str) -> dict:
    d = json.loads(texto)
    pa = d["parametros"]
    return {
        "parametros": Parametros(**{**pa, "fecha": date.fromisoformat(pa["fecha"])}),
        "proveedor": d["proveedor"],
        "condiciones": Condiciones.desde_dict(d["condiciones"]),
        "lineas": [Linea(**{k: _nan(v) if k in ("cantidad", "precio", "peso") else (v or 0.0) if k != "descripcion" else v
                            for k, v in ln.items()}) for ln in d["lineas"]],
        "reconstruido": False,
    }


def _pago_desde_texto(texto: str) -> tuple[str, str, float]:
    """(moneda, pago, valor) a partir del texto de «Forma de pago»."""
    t = str(texto or "")
    if t.startswith("Pago en Bs"):
        return "bs", "divisa", 0.0
    if t.startswith("100% en $"):
        return "usd", "divisa", 0.0
    if t.startswith("100% en Bs"):
        return "usd", "bcv", 0.0
    m = re.match(r"^\$ ([\d.,]+) en \$", t)
    if m:
        return "usd", "monto", _num(m[1])
    m = re.match(r"^([\d.,]+)% en \$", t)
    if m:
        return "usd", "pct", _num(m[1])
    return "usd", "divisa", 0.0


def _reconstruir(det: pd.DataFrame, proveedores: list[Proveedor]) -> dict:
    """Costeos guardados antes de existir la columna «Estado»: se rearman desde el detalle."""
    f0 = det.iloc[0]
    margenes = sorted(float(m) for c in det.columns for m in re.findall(r"^Pieza \+([\d.]+)%$", c))
    iva_txt = str(f0.get("IVA", ""))
    m_iva = re.search(r"IVA ([\d.]+)%", iva_txt)
    iva = float(m_iva[1]) if m_iva else 16.0
    col_precio = next(c for c in det.columns if c.startswith("Precio cotizado"))
    moneda, pago, pago_valor = _pago_desde_texto(f0.get("Forma de pago"))
    if "(Bs)" in col_precio:
        moneda = "bs"
    nombre = str(f0["Proveedor"])
    prov = next((p for p in proveedores if p.nombre.upper() == nombre.upper()), None)
    base = prov.condiciones.a_dict() if prov else {}
    descs = [d for d in (_num(x) for x in str(f0.get("Descuentos %") or "").split("+")) if d]
    cond = Condiciones.desde_dict({
        **base, "moneda": moneda, "pago": pago, "pago_valor": pago_valor,
        "iva_incluido": iva_txt.startswith("Precio con IVA"),
        "iva_base": "10" if "sobre el 10%" in iva_txt else "100",
        "iva_sin_descuento": "sin descuento" in iva_txt,
        "igtf": "IGTF" in str(f0.get("Forma de pago", "")),
        "retencion_iva": "retención" in iva_txt,
        "descuentos": descs, "flete": _num(f0.get("Flete")), "flete_moneda": f0.get("Moneda flete") or "usd",
    })
    tasa = iva / 100 * (0.10 if cond.iva_base == "10" else 1)
    factor_general = 1.0
    for d in descs:
        factor_general *= 1 - d / 100
    lineas, unidades, iva_en_costo = [], [], True
    lista_col, pieza_col = next(c for c in det.columns if c.startswith("Lista s/IVA")), next(c for c in det.columns if c.startswith("Pieza s/IVA"))
    for _, f in det.iterrows():
        precio, peso, lista, pieza = _num(f[col_precio], float("nan")), _num(f["Peso kg"], float("nan")), _num(f[lista_col], float("nan")), _num(f[pieza_col], float("nan"))
        extra = 0.0
        if lista > 0 and pieza > 0 and factor_general > 0:
            extra = round((1 - pieza / lista / factor_general) * 100, 4)
            extra = 0.0 if abs(extra) < 1e-6 else extra
        if lista > 0 and precio > 0 and peso > 0:   # ¿por pieza, por tonelada o por kilo?
            precio_pieza = lista * (1 + tasa) if cond.iva_incluido else lista
            unidades.append(min((abs(precio_pieza - precio), "pieza"), (abs(precio_pieza - precio * peso / 1000), "tonelada"),
                                (abs(precio_pieza - precio * peso), "kg"))[1])
            base_i, iva_i, flete_i, costo = (_num(f.get(c), float("nan")) for c in ("Base $ int.", "IVA $ int.", "Flete $ int.", "Costo pieza $"))
            if costo > 0 and abs(base_i + flete_i - costo) < abs(base_i + iva_i + flete_i - costo):
                iva_en_costo = False
        lineas.append(Linea(str(f["Producto"]), _num(f["Cantidad"], float("nan")), precio, peso,
                            _num(f.get("P3 FERRE"), 0.0), _num(f.get("P3 MCY"), 0.0), extra))
    if unidades:
        cond.precio_por = max(set(unidades), key=unidades.count)
    params = Parametros(
        fecha=date.fromisoformat(str(f0["Fecha pedido"])[:10]), tasa_bcv=_num(f0["Tasa BCV"]), tasa_interna=_num(f0["Tasa interna"]),
        iva=iva, margen_min=margenes[0] if margenes else 17.0, margen_obj=margenes[-1] if margenes else 18.0, iva_en_costo=iva_en_costo,
    )
    return {"parametros": params, "proveedor": {"id": prov.id if prov else "", "nombre": nombre},
            "condiciones": cond, "lineas": lineas, "reconstruido": True}


def abrir_costeo(costeos: pd.DataFrame, costeo_id: str, proveedores: list[Proveedor]) -> dict:
    """Devuelve parámetros, proveedor, condiciones y líneas de un costeo guardado."""
    det = costeos[costeos["COSTEO"].astype(str) == str(costeo_id)]
    if det.empty:
        raise ValueError(f"No existe el costeo {costeo_id}.")
    estado = det["Estado"].dropna().iloc[0] if "Estado" in det.columns and det["Estado"].notna().any() else None
    return _desde_estado(estado) if estado else _reconstruir(det, proveedores)
