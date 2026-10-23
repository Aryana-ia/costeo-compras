"""Costeo de Compras ACEVAL.

Paquete con la lógica de negocio separada de la interfaz (Streamlit):

- ``modelos``   : estructuras de datos (parámetros, condiciones, líneas, resultados).
- ``calculo``   : motor de cálculo puro, sin dependencias de interfaz. Es lo que se prueba.
- ``catalogo``  : lectura de la lista de precios ACEVAL (peso y P3 de FERRE / MCY).
- ``historial`` : lectura del historial de compras y consulta de la última compra.
- ``almacen``   : guardado de perfiles y bases (disco local y, opcionalmente, GitHub).
- ``exportar``  : Excel e imagen PNG para compartir por WhatsApp.
- ``formato``   : formato de números y fechas en estilo venezolano.
"""

__version__ = "1.0.0"
