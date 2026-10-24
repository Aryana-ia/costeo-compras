"""Pruebas del guardado de costeos en el historial."""

from datetime import date, datetime

import pandas as pd
import pytest

from costeo.calculo import calcular
from costeo.historial import Historial, ejemplo
from costeo.modelos import Condiciones, Linea, Parametros, Proveedor
from costeo.registro import filas_costeo, filas_historial, nuevo_id, reemplazar, resumen_costeos

P = Parametros(date(2026, 10, 23), 886.23, 1010.0)
COND = Condiciones(moneda="usd", descuentos=[11], iva_sin_descuento=True, flete=300)
PROV = Proveedor("al", "ACEROS LAMINADOS", COND)
LINEAS = [
    Linea("LAM HN LISA 10,00 MM X 1,200 X 2,400", 40, 254.28, 233.28, 294.91, 294.91),
    Linea("ARENA LAVADA", 10, 5, 0),                     # sin peso: no se registra
    Linea('CABILLA 1/2" X 12 MTS', float("nan"), 11, 11.93, 13.1, 13.1),  # sin cantidad: no se registra
]


def test_id_legible():
    assert nuevo_id(PROV, P, datetime(2026, 10, 23, 20, 15, 3)) == "2026-10-23_ACEROS_LAMINADOS_201503"


def test_filas_historial_solo_productos_completos():
    res = calcular(P, COND, LINEAS)
    h = filas_historial(res, P, PROV, COND, "X1", factura="F-99", observacion="prueba")
    assert len(h) == 1
    f = h.iloc[0]
    assert f.PROVEEDOR == "ACEROS LAMINADOS" and f.FECHA == "2026-10-23" and f.COSTEO == "X1"
    assert f.PRECIO == pytest.approx(226.3092, abs=1e-4)   # pieza sin IVA con 11 % de descuento
    assert f.COSTO_KG == pytest.approx(res.lineas[0].costo_kg, abs=1e-4)
    assert f.DESCUENTO == pytest.approx(11.0) and f.FACTURA == "F-99" and f.TASA == 886.23


def test_reguardar_reemplaza_sin_duplicar():
    res = calcular(P, COND, LINEAS)
    base = ejemplo()
    una = reemplazar(base, filas_historial(res, P, PROV, COND, "X1"), "X1")
    dos = reemplazar(una, filas_historial(res, P, PROV, COND, "X1"), "X1")
    assert len(una) == len(base) + 1 == len(dos)
    otra = reemplazar(dos, filas_historial(res, P, PROV, COND, "X2"), "X2")
    assert len(otra) == len(dos) + 1


def test_historial_excluye_el_costeo_actual():
    res = calcular(P, COND, LINEAS)
    h = Historial(reemplazar(ejemplo(), filas_historial(res, P, PROV, COND, "X1"), "X1"))
    desc = LINEAS[0].descripcion
    assert h.ultima(desc)["COSTEO"] == "X1"
    assert h.sin_costeo("X1").ultima(desc) is None


def test_costeos_detalle_y_resumen():
    res = calcular(P, COND, LINEAS)
    c = filas_costeo(res, P, PROV, COND, "X1", factura="F-99")
    assert {"COSTEO", "Proveedor", "Tasa BCV", "Pieza +17%", "Pieza +18%", "Acción"} <= set(c.columns)
    assert len(c) == len(LINEAS)
    r = resumen_costeos(c)
    # la cabilla sin cantidad no va al historial, pero sí se costea y aparece en el detalle
    assert r.iloc[0].Productos == 3 and r.iloc[0].Subir == 2 and r.iloc[0]["Factura / OC"] == "F-99"
    assert resumen_costeos(pd.DataFrame()).empty


def test_reabrir_costeo_con_estado_da_lo_mismo():
    from costeo.registro import abrir_costeo
    res = calcular(P, COND, LINEAS)
    c = filas_costeo(res, P, PROV, COND, "X1")
    e = abrir_costeo(c, "X1", [PROV])
    assert not e["reconstruido"]
    res2 = calcular(e["parametros"], e["condiciones"], e["lineas"])
    assert res2.lineas[0].costo_pieza == pytest.approx(res.lineas[0].costo_pieza)
    assert e["condiciones"].clave() == COND.clave()


def test_reabrir_costeo_antiguo_sin_estado():
    """Costeos guardados antes de la columna Estado se rearman desde el detalle."""
    from costeo.registro import abrir_costeo
    cond = Condiciones(moneda="usd", descuentos=[11], iva_sin_descuento=True, flete=300, pago="monto", pago_valor=5000)
    lineas = [Linea("A", 40, 254.28, 233.28, 294.91, 294.91, 4.0), Linea("B", 100, 9.21, 8.36, 11, 11)]
    res = calcular(P, cond, lineas)
    c = filas_costeo(res, P, PROV, cond, "X1").drop(columns="Estado")
    e = abrir_costeo(c, "X1", [PROV])
    assert e["reconstruido"]
    assert e["condiciones"].pago == "monto" and e["condiciones"].pago_valor == pytest.approx(5000)
    assert e["lineas"][0].desc_extra == pytest.approx(4.0)
    res2 = calcular(e["parametros"], e["condiciones"], e["lineas"])
    for a, b in zip(res.lineas, res2.lineas):
        assert b.costo_pieza == pytest.approx(a.costo_pieza)
