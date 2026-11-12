"""La lectura de la tasa BCV se prueba con HTML de muestra (sin internet)."""

from datetime import date

import pytest

from costeo import tasas
from costeo.modelos import ErrorDeDatos

HTML = """
<div id="euro" class="col-sm-12"><strong> 1.030,25000000 </strong></div>
<div id="dolar" class="col-sm-12 col-xs-12 ">
  <div class="field-content"><div class="row recuadrotsmc">
    <div class="col-sm-6 col-xs-6"><span> USD</span></div>
    <div class="col-sm-6 col-xs-6 centrado"><strong> 210,50120000 </strong></div>
  </div></div>
</div>
<div class="pull-right dinpro center">Fecha Valor:
  <span class="date-display-single" property="dc:date" datatype="xsd:dateTime" content="2026-10-26T00:00:00-04:00">Lunes, 26 Octubre  2026</span>
</div>
"""


def test_lee_dolar_y_fecha_valor():
    t = tasas.leer_html_bcv(HTML)
    assert t.valor == pytest.approx(210.5012)
    assert t.fecha_valor == date(2026, 10, 26)


def test_html_sin_dolar():
    with pytest.raises(ErrorDeDatos):
        tasas.leer_html_bcv("<html></html>")


def test_usa_respaldo_si_el_bcv_falla(monkeypatch):
    def falla(moneda="usd"):
        raise tasas.requests.ConnectionError("sin conexión")
    monkeypatch.setattr(tasas, "_desde_bcv", falla)
    monkeypatch.setattr(tasas, "_desde_respaldo", lambda moneda="usd": tasas.TasaBCV(211.0, None, "ve.dolarapi.com"))
    assert tasas.obtener_tasa_bcv().fuente == "ve.dolarapi.com"


def test_error_claro_si_fallan_ambas(monkeypatch):
    def falla(moneda="usd"):
        raise tasas.requests.ConnectionError("sin conexión")
    monkeypatch.setattr(tasas, "_desde_bcv", falla)
    monkeypatch.setattr(tasas, "_desde_respaldo", falla)
    with pytest.raises(ErrorDeDatos, match="Escríbela a mano"):
        tasas.obtener_tasa_bcv()


def test_lee_el_euro():
    t = tasas.leer_html_bcv(HTML, "eur")
    assert t.valor == pytest.approx(1030.25)
    assert t.fecha_valor == date(2026, 10, 26)


def test_obtener_ambas_con_una_consulta(monkeypatch):
    monkeypatch.setattr(tasas, "_html_bcv", lambda: HTML)
    t = tasas.obtener_tasas_bcv()
    assert t["usd"].valor == pytest.approx(210.5012) and t["eur"].valor == pytest.approx(1030.25)
