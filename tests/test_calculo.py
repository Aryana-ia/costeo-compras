"""Pruebas del motor de cálculo con casos verificados a mano.

Tasas de referencia: BCV 210,5 · interna 285 → BCV ÷ interna = 0,738596…
"""

from datetime import date

import pytest

from costeo.calculo import calcular, redondear_arriba
from costeo.modelos import Condiciones, ErrorDeDatos, Linea, Parametros

BCV, INT = 210.5, 285.0
F = BCV / INT


def params(**kw):
    base = dict(fecha=date(2026, 10, 23), tasa_bcv=BCV, tasa_interna=INT)
    base.update(kw)
    return Parametros(**base)


def cabilla_media(cant=1500, precio=11.20, p3=12.40):
    return Linea("CABILLA 1/2\" X 12 MTS", cant, precio, 11.93, p3, p3)


# --------------------------------------------------------------------------- UNICOM
def test_unicom_50_50_iva_en_bs_bcv():
    cond = Condiciones(moneda="usd", pago="pct", pago_valor=50, flete=1100)
    r = calcular(params(), cond, [cabilla_media()]).lineas[0]
    base_int = 11.20 * (0.5 + 0.5 * F)
    iva_int = 11.20 * 0.16 * F
    flete = 1100 / 32000 * 11.93
    assert r.base_int == pytest.approx(base_int)
    assert r.iva_int == pytest.approx(iva_int)
    assert r.flete_pieza == pytest.approx(flete)
    assert r.costo_pieza == pytest.approx(11.4698, abs=1e-4)
    assert r.costo_kg == pytest.approx(0.9614, abs=1e-4)
    assert r.costo_obj == pytest.approx(13.5344, abs=1e-4)
    assert r.accion == "SUBIR"  # P3 12,40 < 11,4698 × 1,17


def test_plan_de_pago_unicom():
    cond = Condiciones(moneda="usd", pago="pct", pago_valor=50, flete=0)
    res = calcular(params(), cond, [cabilla_media(cant=100)])
    total = 11.20 * 100
    assert res.plan.usd == pytest.approx(total / 2)
    assert res.plan.bs_base == pytest.approx(total / 2 * BCV)
    assert res.plan.bs_iva == pytest.approx(total * 0.16 * BCV)
    assert res.plan.gasto_int == pytest.approx(total / 2 + total / 2 * F + total * 0.16 * F)


# --------------------------------------------------------------------------- COMPLEJO
def test_complejo_monto_fijo_en_dolares():
    lineas = [
        Linea("CABILLA 1/2", 2000, 11.10, 11.93, 12.40, 12.40),
        Linea("CABILLA 3/8", 1100, 6.25, 6.72, 6.55, 6.55),
    ]
    total = 2000 * 11.10 + 1100 * 6.25  # 29.075
    cond = Condiciones(moneda="usd", pago="monto", pago_valor=13000)
    res = calcular(params(), cond, lineas)
    d = 13000 / total
    assert res.porcion_divisa == pytest.approx(d)
    assert res.plan.usd == pytest.approx(13000)
    assert res.plan.bs_base == pytest.approx((total - 13000) * BCV)
    assert res.lineas[0].base_int == pytest.approx(11.10 * (d + (1 - d) * F))


def test_monto_mayor_que_total_se_limita_y_avisa():
    cond = Condiciones(moneda="usd", pago="monto", pago_valor=999999)
    res = calcular(params(), cond, [cabilla_media(cant=10)])
    assert res.porcion_divisa == 1.0
    assert any("mayor que el total" in a for a in res.avisos)


# --------------------------------------------------------------------------- IVA
def test_precio_con_iva_se_quita_y_descuento_va_sobre_la_base():
    cond = Condiciones(moneda="usd", iva_incluido=True, descuentos=[10], pago="divisa")
    r = calcular(params(), cond, [cabilla_media(precio=116.0)]).lineas[0]
    assert r.lista_sin_iva == pytest.approx(100.0)
    assert r.pieza_sin_iva == pytest.approx(90.0)        # descuento sobre la base
    assert r.iva_pieza == pytest.approx(14.4)            # 16 % de la base neta
    assert r.iva_int == pytest.approx(14.4 * F)          # IVA en Bs a BCV


def test_iva_full_sin_descuento_aceros_laminados():
    """El descuento baja la base, pero el IVA se calcula sobre la base completa."""
    cond = Condiciones(moneda="usd", descuentos=[10], iva_sin_descuento=True, pago="divisa")
    r = calcular(params(), cond, [cabilla_media(precio=100)]).lineas[0]
    assert r.pieza_sin_iva == pytest.approx(90.0)     # base con descuento
    assert r.iva_pieza == pytest.approx(16.0)         # IVA full: 16 % de 100, no de 90
    assert r.pieza_con_iva == pytest.approx(106.0)
    assert r.base_int == pytest.approx(90.0)
    assert r.iva_int == pytest.approx(16.0 * F)       # el IVA se sigue pagando en Bs a BCV
    con_descuento = calcular(params(), Condiciones(moneda="usd", descuentos=[10]), [cabilla_media(precio=100)]).lineas[0]
    assert con_descuento.iva_pieza == pytest.approx(14.4)


def test_iva_full_con_precio_que_ya_trae_iva():
    cond = Condiciones(moneda="usd", iva_incluido=True, descuentos=[10], iva_sin_descuento=True)
    r = calcular(params(), cond, [cabilla_media(precio=116)]).lineas[0]
    assert r.lista_sin_iva == pytest.approx(100.0)
    assert r.pieza_sin_iva == pytest.approx(90.0)
    assert r.iva_pieza == pytest.approx(16.0)


def test_iva_sobre_el_10_por_ciento():
    cond = Condiciones(moneda="usd", iva_base="10")
    r = calcular(params(), cond, [cabilla_media(precio=100)]).lineas[0]
    assert r.iva_pieza == pytest.approx(1.6)


def test_iva_fuera_del_costo():
    cond = Condiciones(moneda="usd")
    r = calcular(params(iva_en_costo=False), cond, [cabilla_media(precio=100)]).lineas[0]
    assert r.costo_pieza == pytest.approx(100.0)


def test_descuentos_en_cascada():
    cond = Condiciones(moneda="usd", descuentos=[3, 2])
    r = calcular(params(), cond, [cabilla_media(precio=100)]).lineas[0]
    assert r.pieza_sin_iva == pytest.approx(100 * 0.97 * 0.98)


# --------------------------------------------------------------------------- Bs
def test_cotizacion_en_bolivares_divide_entre_interna():
    cond = Condiciones(moneda="bs", iva_incluido=True)
    r = calcular(params(), cond, [cabilla_media(precio=3306.0)]).lineas[0]
    base = 3306 / 1.16
    assert r.base_int == pytest.approx(base / INT)
    assert r.iva_int == pytest.approx(base * 0.16 / INT)


# --------------------------------------------------------------------------- unidades
def test_precio_por_tonelada():
    cond = Condiciones(moneda="usd", precio_por="tonelada")
    r = calcular(params(), cond, [cabilla_media(precio=1000)]).lineas[0]
    assert r.precio_pieza == pytest.approx(11.93)


# --------------------------------------------------------------------------- flete
def test_flete_en_bs_y_carga_real():
    cond = Condiciones(moneda="usd", flete=285000, flete_moneda="bs", flete_carga_real=True)
    res = calcular(params(), cond, [cabilla_media(cant=1000)])  # 11.930 kg
    assert res.plan.flete_int == pytest.approx(1000)
    assert res.flete_kg == pytest.approx(1000 / 11930)
    assert res.totales.flete_asignado == pytest.approx(1000)


@pytest.mark.parametrize("piezas,flete_total", [(3353, 375.0), (1676.5, 187.5)])  # ≈40 t y ≈20 t
def test_flete_como_tarifa_por_kilo(piezas, flete_total):
    """300 $ por gandola de 32 t = 0,009375 $/kg, cualquiera sea el peso del pedido."""
    cond = Condiciones(moneda="usd", flete=300)
    res = calcular(params(), cond, [Linea("X", piezas, 10, 11.93, 20, 20)])
    assert res.flete_kg == pytest.approx(300 / 32000)
    assert res.lineas[0].flete_pieza == pytest.approx(11.93 * 300 / 32000)
    assert res.plan.flete_int == pytest.approx(flete_total, rel=1e-3)
    assert res.plan.gasto_int == pytest.approx(res.totales.costo)  # el gasto total cuadra con las piezas


# --------------------------------------------------------------------------- decisión
@pytest.mark.parametrize("p3,accion", [(1.10, "SUBIR"), (1.175, "REVISAR"), (1.18, "MANTENER")])
def test_semaforo(p3, accion):
    cond = Condiciones(moneda="usd")
    linea = Linea("X", 1, 1.0, 1.0, p3, p3)
    r = calcular(params(iva=0), cond, [linea]).lineas[0]
    assert r.costo_pieza == pytest.approx(1.0)
    assert r.accion == accion


def test_errores_de_datos():
    res = calcular(params(tasa_bcv=0), Condiciones(), [cabilla_media()])
    assert "Falta la tasa BCV." in res.errores
    sin_peso = calcular(params(), Condiciones(), [Linea("ARENA", 10, 5, 0)]).lineas[0]
    assert sin_peso.error and sin_peso.accion == "ERROR"
    with pytest.raises(ErrorDeDatos):
        Condiciones(pago="cheque")


def test_redondeo_hacia_arriba():
    assert redondear_arriba(1.23451) == 1.2346
    assert redondear_arriba(1.2345) == 1.2345
