"""Lectura de la lista de precios ACEVAL.

Acepta dos formatos:

1. **Listado maestro** (``Listado_de_Precios_Nacional_Actualizado<FECHA>.xlsx``,
   hoja CONSOLIDADO): una fila por producto y tienda, con columnas
   ``TIENDA``, ``PRODUCTO``, ``PESO KG`` y ``P3 $``. Se toman las filas de FERRE y MCY.
2. **Formato simple**: columnas ``DESCRIPCION``, ``PESO``, ``P3 FERRE`` y
   (opcional) ``P3 MCY``.

En ambos casos el resultado es un DataFrame normalizado con las columnas
``DESCRIPCION, CODIGO, PESO, P3_FERRE, P3_MCY, CLAVE`` (CLAVE = descripción
normalizada, que es como se enlaza con las líneas y el historial).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

from .formato import normalizar
from .modelos import ErrorDeDatos, _num

COLUMNAS = ["DESCRIPCION", "CODIGO", "PESO", "P3_FERRE", "P3_MCY"]
FILAS_BUSQUEDA_ENCABEZADO = 15


def _hnorm(h) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[$.:]", " ", normalizar(h))).strip()


def leer_hoja(archivo, preferida: str = "CONSOLIDADO") -> tuple[str, pd.DataFrame]:
    """Lee la hoja ``preferida`` (o la primera) sin encabezado.

    ``archivo`` puede ser una ruta, bytes o un objeto tipo archivo (lo que
    entrega ``st.file_uploader``). Los CSV también se aceptan.
    """
    nombre = getattr(archivo, "name", str(archivo) if isinstance(archivo, str) else "")
    datos = archivo.getvalue() if hasattr(archivo, "getvalue") else archivo
    if isinstance(datos, bytes):
        datos = io.BytesIO(datos)
    try:
        if nombre.lower().endswith(".csv"):
            return "CSV", pd.read_csv(datos, header=None, dtype=object, sep=None, engine="python")
        libro = pd.ExcelFile(datos)
        hoja = next((h for h in libro.sheet_names if normalizar(h) == preferida), libro.sheet_names[0])
        return hoja, libro.parse(hoja, header=None, dtype=object)
    except Exception as e:  # noqa: BLE001 - el mensaje se muestra a la usuaria
        raise ErrorDeDatos(f"No se pudo leer el archivo como Excel ({e}).") from e


def buscar_encabezado(crudo: pd.DataFrame, prueba) -> tuple[int, list[str]] | None:
    for i in range(min(FILAS_BUSQUEDA_ENCABEZADO, len(crudo))):
        enc = [_hnorm(v) for v in crudo.iloc[i].tolist()]
        if prueba(enc):
            return i, enc
    return None


def _col(enc: list[str], cond) -> int:
    return next((i for i, h in enumerate(enc) if cond(h)), -1)


@dataclass
class LecturaLista:
    """Resultado de leer el Excel, antes de elegir tiendas y guardar."""

    archivo: str
    hoja: str
    formato: str                 # "maestro" | "simple"
    datos: pd.DataFrame
    c_desc: int
    c_peso: int
    c_cod: int
    c_p3: int = -1
    c_tienda: int = -1
    c_p3_ferre: int = -1
    c_p3_mcy: int = -1
    tiendas: list[str] = field(default_factory=list)
    ferre: str = ""
    mcy: str = ""

    def construir(self, ferre: str | None = None, mcy: str | None = None) -> pd.DataFrame:
        """Arma el catálogo normalizado (un producto por fila)."""
        ferre = self.ferre if ferre is None else ferre
        mcy = self.mcy if mcy is None else mcy
        d = self.datos
        filas: dict[str, list] = {}

        def agregar(desc, cod, peso, p3f, p3m):
            texto = "" if desc is None else str(desc).strip()
            if not texto or texto.lower() == "nan":
                return
            k = normalizar(texto)
            cur = filas.setdefault(k, [texto, "", float("nan"), float("nan"), float("nan")])
            cod = "" if cod is None or str(cod).lower() == "nan" else str(cod).strip()
            if cod and not cur[1]:
                cur[1] = cod
            if not cur[2] > 0 and peso > 0:
                cur[2] = peso
            if p3f is not None and p3f > 0:
                cur[3] = p3f
            if p3m is not None and p3m > 0:
                cur[4] = p3m

        for fila in d.itertuples(index=False):
            fila = list(fila)
            cod = fila[self.c_cod] if self.c_cod >= 0 else ""
            peso = _num(fila[self.c_peso], float("nan"))
            if self.formato == "maestro":
                if not (ferre and mcy):
                    raise ErrorDeDatos("Elige cuál tienda es FERRE y cuál es MCY.")
                tienda = str(fila[self.c_tienda] or "").strip()
                if tienda not in (ferre, mcy):
                    continue
                p3 = _num(fila[self.c_p3], float("nan"))
                agregar(fila[self.c_desc], cod, peso, p3 if tienda == ferre else None, p3 if tienda == mcy else None)
            else:
                p3m = _num(fila[self.c_p3_mcy], float("nan")) if self.c_p3_mcy >= 0 else None
                agregar(fila[self.c_desc], cod, peso, _num(fila[self.c_p3_ferre], float("nan")), p3m)

        df = pd.DataFrame(list(filas.values()), columns=COLUMNAS)
        # FERRE y MCY van al mismo nivel: si falta uno, se completa con el otro
        df["P3_MCY"] = df["P3_MCY"].where(df["P3_MCY"] > 0, df["P3_FERRE"])
        df["P3_FERRE"] = df["P3_FERRE"].where(df["P3_FERRE"] > 0, df["P3_MCY"])
        df["PESO"] = df["PESO"].round(4)
        df["CLAVE"] = df["DESCRIPCION"].map(normalizar)
        return df.sort_values("DESCRIPCION", key=lambda s: s.str.upper()).reset_index(drop=True)


def leer_lista_precios(archivo) -> LecturaLista:
    hoja, crudo = leer_hoja(archivo)
    nombre = getattr(archivo, "name", str(archivo))
    enc = buscar_encabezado(crudo, lambda h: any(x == "PRODUCTO" or x.startswith("DESCRIPCION") for x in h))
    if not enc:
        raise ErrorDeDatos("No encontré una columna PRODUCTO o DESCRIPCION en las primeras 15 filas.")
    i, h = enc
    datos = crudo.iloc[i + 1:].dropna(how="all").reset_index(drop=True)

    c_desc = _col(h, lambda x: x == "DESCRIPCION UNICA")
    if c_desc < 0:
        c_desc = _col(h, lambda x: x == "PRODUCTO")
    if c_desc < 0:
        c_desc = _col(h, lambda x: x.startswith("DESCRIPCION"))
    c_peso = _col(h, lambda x: "PESO" in x)
    c_cod = _col(h, lambda x: x.startswith("CODIGO"))
    c_tienda = _col(h, lambda x: x == "TIENDA")
    c_p3 = _col(h, lambda x: x in ("P3", "P3 USD", "P 3"))
    c_p3f = _col(h, lambda x: "P3" in x and "FERRE" in x)
    c_p3m = _col(h, lambda x: "P3" in x and ("MCY" in x or "MARACAY" in x))
    encontradas = ", ".join(x for x in h if x)

    if c_peso < 0:
        raise ErrorDeDatos(f"Falta la columna de PESO. Columnas encontradas: {encontradas}")

    base = dict(archivo=nombre, hoja=hoja, datos=datos, c_desc=c_desc, c_peso=c_peso, c_cod=c_cod)
    if c_tienda >= 0 and c_p3 >= 0:
        tiendas = sorted({str(t).strip() for t in datos.iloc[:, c_tienda].dropna() if str(t).strip()})

        def adivinar(patron):
            return next((t for t in tiendas if re.search(patron, normalizar(t))), "")

        return LecturaLista(formato="maestro", c_p3=c_p3, c_tienda=c_tienda, tiendas=tiendas,
                            ferre=adivinar(r"FERRE"), mcy=adivinar(r"MARACAY|MCY"), **base)
    if c_p3f >= 0:
        return LecturaLista(formato="simple", c_p3_ferre=c_p3f, c_p3_mcy=c_p3m, **base)
    raise ErrorDeDatos(
        "No reconozco el formato. Necesito TIENDA + P3 $ (listado maestro) o columnas "
        f"«P3 FERRE» y «P3 MCY». Columnas encontradas: {encontradas}"
    )


def resumen(df: pd.DataFrame) -> dict[str, int]:
    distintos = ((df["P3_FERRE"] > 0) & (df["P3_MCY"] > 0) & ((df["P3_MCY"] / df["P3_FERRE"] - 1).abs() > 0.0005))
    return {
        "productos": len(df),
        "sin_peso": int((~(df["PESO"] > 0)).sum()),
        "sin_p3": int((~(df["P3_FERRE"] > 0)).sum()),
        "p3_distinto": int(distintos.sum()),
    }


def ejemplo() -> pd.DataFrame:
    """Lista mínima para que la app se pueda probar sin cargar nada."""
    filas = [
        ['CABILLA 1/2" X 12 MTS', "EJ-001", 11.93, 12.40, 12.40],
        ['CABILLA 3/8" X 12 MTS', "EJ-002", 6.72, 6.55, 6.55],
        ['CABILLA 5/8" X 12 MTS', "EJ-003", 18.64, 19.90, 19.90],
        ["TUBO ESTRUCTURAL 100X100X2.5 X 6 MTS", "EJ-004", 44.6, 66.50, 66.50],
        ["LAMINA GALVANIZADA CAL 24 1.22X2.44", "EJ-005", 9.8, 12.90, 12.90],
        ['ANGULO 1-1/2" X 3/16" X 6 MTS', "EJ-006", 12.6, 14.10, 14.10],
    ]
    df = pd.DataFrame(filas, columns=COLUMNAS)
    df["CLAVE"] = df["DESCRIPCION"].map(normalizar)
    return df
