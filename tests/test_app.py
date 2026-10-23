"""Prueba de humo de la interfaz con el ejecutor de pruebas de Streamlit (sin navegador).

Nota: ``AppTest`` todavía no puede interactuar con ``st.data_editor``, así que aquí
solo se verifica que la página arranca sin errores y muestra sus secciones.
Los flujos completos (agregar productos, cambiar condiciones, exportar) se
verifican con el motor de cálculo en ``test_calculo.py``.
"""

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_arranca_sin_errores():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert [s.value for s in at.subheader][:3] == [
        "1 · Proveedor y forma de pago", "2 · Productos del pedido", "3 · Resultado",
    ]
    assert any("Agrega productos" in i.value for i in at.info)
    assert {"UNICOM", "COMPLEJO"} <= {p.nombre for p in at.session_state["proveedores"]}
