"""Pruebas de lectura de la lista de precios, el historial y el almacén local."""

import io
import json

import pandas as pd
import pytest

from costeo.almacen import Almacen
from costeo.catalogo import leer_lista_precios, resumen
from costeo.historial import Historial, leer_historial, plantilla_excel
from costeo.modelos import Condiciones, ErrorDeDatos, Proveedor


def excel(df: pd.DataFrame, hoja="CONSOLIDADO", nombre="lista.xlsx", filas_antes=0) -> io.BytesIO:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name=hoja, startrow=filas_antes)
    buf.seek(0)
    buf.name = nombre
    return buf


def test_listado_maestro_toma_ferre_y_mcy():
    df = pd.DataFrame({
        "CODNIA": [1, 1, 1, 2],
        "TIENDA": ["ACEROS DE VALENCIA PLANTA", "FERRETERIA ACEVAL", "ACEVAL MARACAY", "FERRETERIA ACEVAL"],
        "CODIGO": ["A1", "F1", "M1", "F2"],
        "PRODUCTO": ['CABILLA 1/2" X 12 MTS'] * 3 + ["ÁNGULO 1\""],
        "P3 $": [12.5, 12.40, 12.40, 9.0],
        "PESO KG": [11.93, 11.93, 11.93, 5.0],
    })
    lec = leer_lista_precios(excel(df, filas_antes=2))
    assert lec.formato == "maestro"
    assert lec.ferre == "FERRETERIA ACEVAL" and lec.mcy == "ACEVAL MARACAY"
    cat = lec.construir()
    fila = cat.set_index("CLAVE").loc['CABILLA 1/2" X 12 MTS']
    assert fila.P3_FERRE == 12.40 and fila.P3_MCY == 12.40 and fila.PESO == 11.93
    angulo = cat.set_index("CLAVE").loc['ANGULO 1"']  # sin acento en la clave
    assert angulo.P3_MCY == 9.0  # MCY faltante se completa con FERRE
    assert resumen(cat)["productos"] == 2


def test_formato_simple_y_columna_faltante():
    df = pd.DataFrame({"DESCRIPCION": ["X"], "PESO": [2], "P3 FERRE": [3], "P3 MCY": [3.1]})
    cat = leer_lista_precios(excel(df, hoja="Hoja1")).construir()
    assert cat.iloc[0].P3_MCY == 3.1
    with pytest.raises(ErrorDeDatos, match="PESO"):
        leer_lista_precios(excel(pd.DataFrame({"DESCRIPCION": ["X"], "P3 FERRE": [1]})))


def test_historial_desde_plantilla():
    buf = io.BytesIO(plantilla_excel())
    buf.name = "historial.xlsx"
    lec = leer_historial(buf)
    assert len(lec.datos) == 1
    assert lec.datos.iloc[0].FECHA == "2026-09-18"
    h = Historial(lec.datos)
    assert h.ultima('cabilla 1/2" x 12 mts')["PROVEEDOR"] == "UNICOM"


def test_historial_omite_filas_incompletas():
    df = pd.DataFrame({"FECHA": ["01/02/2026", None], "PROVEEDOR": ["A", "B"],
                       "DESCRIPCION": ["X", "Y"], "PRECIO": [10, 5]})
    lec = leer_historial(excel(df, hoja="HISTORIAL"))
    assert len(lec.datos) == 1 and lec.filas_omitidas == [3]


def test_almacen_local_ida_y_vuelta(tmp_path):
    a = Almacen(tmp_path)
    provs = [Proveedor("unicom", "UNICOM", Condiciones(pago="pct", pago_valor=50, descuentos=[3]))]
    a.guardar_proveedores(provs)
    leidos = a.cargar_proveedores()
    assert leidos[0].condiciones.clave() == provs[0].condiciones.clave()
    json.loads((tmp_path / "proveedores.json").read_text(encoding="utf-8"))
    df = pd.DataFrame({"DESCRIPCION": ["X"], "CODIGO": ["007"], "PESO": [1.5]})
    a.guardar_tabla("lista_precios.csv", df, "prueba")
    leido, origen = a.cargar_tabla("lista_precios.csv")
    assert origen == "disco" and leido.iloc[0].CODIGO == "007"


def test_perfiles_por_defecto_validos():
    a = Almacen()
    nombres = [p.nombre for p in a.cargar_proveedores()]
    assert {"UNICOM", "COMPLEJO"} <= set(nombres)
