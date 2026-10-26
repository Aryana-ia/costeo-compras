"""Motor de cálculo del costeo de compras.

Función principal: :func:`calcular`. Es pura (no lee archivos ni usa Streamlit),
así se puede probar con ``pytest`` y reutilizar desde otros scripts.

Pasos, idénticos para todos los proveedores
-------------------------------------------
1. Precio por pieza en la moneda de la cotización
   (si cotiza por tonelada: precio × peso ÷ 1000; por kilo: precio × peso).
2. Si el precio trae IVA, se le quita: base = precio ÷ (1 + IVA efectivo).
3. Los descuentos se aplican SIEMPRE sobre la base, en cascada.
4. IVA = base neta × 16 %  (o × 16 % × 10 % si el proveedor cobra IVA sobre el 10 %).
   Si el proveedor calcula el IVA sin el descuento (ACEROS LAMINADOS), el IVA es
   «full»: base ANTES de descuentos × 16 %. La base que se paga sí lleva el descuento.
5. Todo se lleva a dólares a tasa interna ("$ interno"):

   * Cotización en Bs: base e IVA ÷ tasa interna.
   * Cotización en $:
       - base pagada en $ (o en Bs a tasa interna)  → × 1
       - base pagada en Bs a tasa BCV               → × BCV ÷ interna
       - mixto (UNICOM 50/50, COMPLEJO monto fijo)  → parte en $ × 1 + resto × BCV ÷ interna
       - el IVA SIEMPRE se paga en Bs a tasa BCV     → × BCV ÷ interna

6b. IGTF (si aplica): % (3 % por defecto) sobre la parte de la base pagada en dólares.
6. Flete como TARIFA POR KILO: monto de una gandola en $ interno ÷ 32.000 kg
   × peso de la pieza. Ej.: 300 $ ÷ 32.000 = 0,009375 $/kg → un pedido de 40 t
   lleva 375 $ de flete y uno de 20 t, 187,50 $. (Opcional: cobrar la gandola
   completa aunque el pedido pese menos, repartiéndola sobre los kilos reales.)
7. Costo pieza = base + IVA (si se incluye en el costo) + flete.
   Costo kilo = costo pieza ÷ peso.
8. Precio estimado = costo × (1 + 17 %) y × (1 + 18 %), que se compara con el P3:
      P3 < costo +17 %          → SUBIR
      +17 % ≤ P3 < costo +18 %  → REVISAR (margen corto)
      P3 ≥ costo +18 %          → MANTENER
   P3 sugerido = costo × 1,18 redondeado hacia arriba a 4 decimales.
"""

from __future__ import annotations

import math

from .formato import num as _n
from .modelos import (
    Condiciones,
    Linea,
    Parametros,
    PlanDePago,
    Resultado,
    ResultadoLinea,
    Totales,
)

NAN = float("nan")
TOLERANCIA_MCY = 0.0005  # diferencia relativa a partir de la cual P3 MCY ≠ P3 FERRE


def _ok(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def redondear_arriba(valor: float, decimales: int = 4) -> float:
    """Redondea hacia arriba (criterio de precios de ACEVAL)."""
    if not _ok(valor):
        return NAN
    f = 10 ** decimales
    return math.ceil(valor * f - 1e-9) / f


def factor_flete(moneda: str, p: Parametros) -> float:
    """Convierte el monto del flete a $ interno."""
    if moneda == "bs":
        return 1 / p.tasa_interna
    if moneda == "usd_bcv":
        return p.factor_bcv
    return 1.0


def _validar_parametros(p: Parametros) -> list[str]:
    errores = []
    if not p.fecha:
        errores.append("Falta la fecha del pedido: la tasa BCV debe corresponder a una fecha.")
    if not (_ok(p.tasa_bcv) and p.tasa_bcv > 0):
        errores.append("Falta la tasa BCV.")
    if not (_ok(p.tasa_interna) and p.tasa_interna > 0):
        errores.append("Falta la tasa interna.")
    return errores


def calcular(p: Parametros, cond: Condiciones, lineas: list[Linea]) -> Resultado:
    """Calcula el costo de cada línea, los totales y el plan de pago."""
    errores = _validar_parametros(p)
    avisos: list[str] = []
    iva = p.iva / 100
    tasa_iva = iva * 0.10 if cond.iva_base == "10" else iva
    toneladas = cond.toneladas if cond.toneladas > 0 else 32.0
    tasas_ok = not errores

    factor_desc_general = 1.0
    for d in cond.descuentos:
        factor_desc_general *= 1 - d / 100

    # -- Pasos 1 a 4: precio del proveedor en su moneda ----------------------
    res: list[ResultadoLinea] = []
    for ln in lineas:
        r = ResultadoLinea(linea=ln)
        cant = ln.cantidad if _ok(ln.cantidad) and ln.cantidad > 0 else NAN
        if _ok(ln.peso) and ln.peso > 0:
            r.kg_total = ln.peso * cant
        if not (_ok(ln.peso) and ln.peso > 0):
            r.error = "Sin peso (producto por unidad o falta en la lista de precios)"
            res.append(r)
            continue
        if not (_ok(ln.precio) and ln.precio > 0):
            r.error = "Sin precio del proveedor"
            res.append(r)
            continue

        if cond.precio_por == "tonelada":
            r.precio_pieza = ln.precio * ln.peso / 1000
        elif cond.precio_por == "kg":
            r.precio_pieza = ln.precio * ln.peso
        else:
            r.precio_pieza = ln.precio

        r.lista_sin_iva = r.precio_pieza / (1 + tasa_iva) if cond.iva_incluido else r.precio_pieza
        r.factor_desc = factor_desc_general * (1 - (ln.desc_extra or 0) / 100)
        r.pieza_sin_iva = r.lista_sin_iva * r.factor_desc
        base_iva = r.lista_sin_iva if cond.iva_sin_descuento else r.pieza_sin_iva
        r.iva_pieza = base_iva * tasa_iva
        r.pieza_con_iva = r.pieza_sin_iva + r.iva_pieza
        r.kg_sin_iva = r.pieza_sin_iva / ln.peso
        r.kg_con_iva = r.pieza_con_iva / ln.peso
        r.total_sin_iva = r.pieza_sin_iva * cant
        r.total_iva = r.iva_pieza * cant
        r.total_con_iva = r.pieza_con_iva * cant
        res.append(r)

    validas = [r for r in res if _ok(r.pieza_sin_iva) and _ok(r.linea.cantidad) and r.linea.cantidad > 0]
    total_sin = sum(r.total_sin_iva for r in validas)
    total_iva = sum(r.total_iva for r in validas)
    total_kg = sum(r.kg_total for r in validas)
    if any(_ok(r.pieza_sin_iva) and not (_ok(r.linea.cantidad) and r.linea.cantidad > 0) for r in res):
        avisos.append(
            "Hay líneas sin cantidad de piezas: se calcula su costo, pero no entran "
            "en los totales ni en el reparto del pago."
        )

    if not tasas_ok:
        return Resultado(
            lineas=res, totales=Totales(lineas=len(validas), kg=total_kg, sin_iva=total_sin, iva=total_iva),
            plan=PlanDePago(), factor_base=NAN, factor_iva=NAN, porcion_divisa=None,
            flete_kg=NAN, kg_reparto_flete=NAN, tasa_iva_efectiva=tasa_iva,
            errores=errores, avisos=avisos,
        )

    # -- Paso 5: factores a $ interno ----------------------------------------
    f_bcv = p.factor_bcv
    porcion: float | None
    if cond.moneda == "bs":
        factor_base = factor_iva = 1 / p.tasa_interna
        porcion = None
    else:
        factor_iva = f_bcv  # el IVA de una cotización en $ se paga en Bs a BCV
        if cond.pago == "divisa":
            porcion = 1.0
        elif cond.pago == "bcv":
            porcion = 0.0
        elif cond.pago == "pct":
            v = cond.pago_valor
            if not 0 <= v <= 100:
                avisos.append("El % pagado en dólares debe estar entre 0 y 100.")
            porcion = min(max(v / 100, 0.0), 1.0)
        else:  # monto fijo en $
            v = cond.pago_valor
            if v <= 0:
                avisos.append("Indica el monto que se paga en dólares.")
            if total_sin > 0 and v > total_sin:
                avisos.append(
                    f"El monto en dólares ({_n(v)}) es mayor que el total sin IVA "
                    f"({_n(total_sin)}): se toma el 100 % en dólares."
                )
            porcion = min(max(v / total_sin, 0.0), 1.0) if total_sin > 0 else 0.0
        factor_base = porcion + (1 - porcion) * f_bcv

    # -- Paso 6: flete --------------------------------------------------------
    kg_gandola = toneladas * 1000
    kg_reparto = min(total_kg, kg_gandola) if cond.flete_carga_real and total_kg > 0 else kg_gandola
    flete_int = cond.flete * factor_flete(cond.flete_moneda, p)
    flete_kg = flete_int / kg_reparto if kg_reparto > 0 else 0.0
    if cond.flete <= 0:
        avisos.append("El flete está en 0: el costo no incluye flete.")

    # -- Pasos 6 a 8 por línea -----------------------------------------------
    m_min, m_obj = p.margen_min / 100, p.margen_obj / 100
    for r in res:
        if not _ok(r.pieza_sin_iva):
            continue
        ln = r.linea
        r.base_int = r.pieza_sin_iva * factor_base
        r.iva_int = r.iva_pieza * factor_iva
        r.flete_pieza = flete_kg * ln.peso
        # IGTF: % sobre la parte de la base que se paga en dólares (no aplica al IVA ni a lo pagado en Bs)
        r.igtf_pieza = r.pieza_sin_iva * porcion * cond.igtf_pct / 100 if cond.igtf and porcion else 0.0
        r.costo_pieza = r.base_int + (r.iva_int if p.iva_en_costo else 0.0) + r.flete_pieza + r.igtf_pieza
        r.costo_kg = r.costo_pieza / ln.peso
        r.costo_min = r.costo_pieza * (1 + m_min)
        r.costo_obj = r.costo_pieza * (1 + m_obj)
        r.kg_min = r.costo_min / ln.peso
        r.kg_obj = r.costo_obj / ln.peso
        r.p3_sugerido = redondear_arriba(r.costo_obj)
        p3, p3m = ln.p3_ferre or 0.0, ln.p3_mcy or 0.0
        r.mcy_distinto = p3 > 0 and p3m > 0 and abs(p3m / p3 - 1) > TOLERANCIA_MCY
        if p3 > 0:
            r.kilo_p3 = p3 / ln.peso
            r.dif_min = p3 / r.costo_min - 1
            r.dif_obj = p3 / r.costo_obj - 1
            if p3 < r.costo_min:
                r.accion = "SUBIR"
            elif p3 < r.costo_obj:
                r.accion = "REVISAR"
            else:
                r.accion = "MANTENER"
        else:
            r.accion = "ERROR"
            r.error = "Sin P3 de FERRE"

    # -- Totales y plan de pago ------------------------------------------------
    tot = Totales(
        lineas=len(validas),
        piezas=sum(r.linea.cantidad for r in validas),
        kg=total_kg,
        sin_iva=total_sin,
        iva=total_iva,
        base_int=total_sin * factor_base,
        iva_int=total_iva * factor_iva,
        flete_asignado=sum(r.flete_pieza * r.linea.cantidad for r in validas),
        igtf=sum(r.igtf_pieza * r.linea.cantidad for r in validas),
        costo=sum(r.costo_pieza * r.linea.cantidad for r in validas),
    )
    if cond.moneda == "bs":
        plan = PlanDePago(bs_base=total_sin, bs_iva=total_iva)
    else:
        assert porcion is not None
        plan = PlanDePago(
            usd=total_sin * porcion,
            usd_base_en_bs=total_sin * (1 - porcion),
            usd_iva=total_iva,
            bs_base=total_sin * (1 - porcion) * p.tasa_bcv,
            bs_iva=total_iva * p.tasa_bcv,
        )
    # El flete del pedido es la tarifa por kilo × los kilos pedidos (lo mismo que suman los productos),
    # no el monto fijo de una gandola: así el gasto total cuadra con el costo de las piezas.
    plan.flete_int = tot.flete_asignado
    plan.igtf = tot.igtf
    plan.retencion_pct = cond.retencion_pct if cond.retencion_iva else 0.0  # solo informativo
    plan.tasa_bcv, plan.tasa_interna = p.tasa_bcv, p.tasa_interna
    plan.gasto_int = tot.base_int + (tot.iva_int if p.iva_en_costo else 0.0) + tot.flete_asignado + tot.igtf
    if cond.igtf and cond.moneda == "bs":
        avisos.append("El IGTF está activado, pero la cotización es en bolívares: no hay base en dólares, así que no se cobra.")

    return Resultado(
        lineas=res, totales=tot, plan=plan, factor_base=factor_base, factor_iva=factor_iva,
        porcion_divisa=porcion, flete_kg=flete_kg, kg_reparto_flete=kg_reparto,
        tasa_iva_efectiva=tasa_iva, errores=errores, avisos=avisos,
    )


def describir_pago(cond: Condiciones) -> str:
    """Texto corto de la forma de pago, para pantallas, imagen y Excel."""
    if cond.moneda == "bs":
        return "Pago en Bs (÷ tasa interna)"
    v = cond.pago_valor
    igtf = f" · IGTF {cond.igtf_pct:g}%" if cond.igtf else ""
    return {
        "divisa": "100% en $ o Bs a tasa interna",
        "bcv": "100% en Bs a tasa BCV",
        "pct": f"{v:g}% en $ · {100 - v:g}% en Bs a BCV",
        "monto": f"$ {_n(v)} en $ · resto en Bs a BCV",
    }[cond.pago] + igtf


def describir_iva(cond: Condiciones, iva: float) -> str:
    base = f"IVA {iva:g}% sobre el 10%" if cond.iva_base == "10" else f"IVA {iva:g}%"
    if cond.iva_sin_descuento and cond.descuentos:
        base += " sin descuento (full)"
    if cond.retencion_iva:
        base += f" · retención {cond.retencion_pct:g}%"
    return ("Precio con IVA" if cond.iva_incluido else "Precio sin IVA") + " · " + base
