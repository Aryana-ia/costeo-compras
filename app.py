"""Costeo de Compras ACEVAL — interfaz Streamlit.

Ejecutar en local:   streamlit run app.py
La lógica de negocio vive en el paquete ``costeo`` (ver README.md).
"""

from __future__ import annotations

import uuid
from datetime import date

import pandas as pd
import streamlit as st

from costeo import __version__
from costeo import formato as fmt
from costeo.almacen import ARCH_HISTORIAL, ARCH_LISTA, Almacen, ConfigGitHub
from costeo.calculo import calcular, describir_iva, describir_pago
from costeo.catalogo import ejemplo as catalogo_ejemplo
from costeo.catalogo import leer_lista_precios, resumen
from costeo.exportar import excel, imagen, tabla
from costeo.historial import Historial, leer_historial, plantilla_excel
from costeo.historial import ejemplo as historial_ejemplo
from costeo.modelos import (
    FORMAS_PAGO, IVA_BASE, MONEDAS, MONEDAS_FLETE, PRECIO_POR,
    Condiciones, ErrorDeDatos, Linea, Parametros, Proveedor,
)

st.set_page_config(page_title="Costeo de Compras ACEVAL", page_icon="🧮", layout="wide")

COLS_LINEAS = ["Producto", "Cantidad", "Precio", "Desc. extra %", "Peso kg", "P3 FERRE", "P3 MCY"]
COLORES_ACCION = {
    "SUBIR": "background-color:#FBE4E4;color:#B91C1C;font-weight:700",
    "REVISAR": "background-color:#FBF1D6;color:#A16207;font-weight:700",
    "MANTENER": "background-color:#E3F4E8;color:#15803D;font-weight:700",
    "ERROR": "background-color:#B91C1C;color:#FFFFFF;font-weight:700",
}

ss = st.session_state


def md(texto) -> str:
    """Escapa '$' para que Streamlit no lo lea como fórmula matemática (LaTeX)."""
    return str(texto).replace("$", r"\$")


# =============================================================================
# Arranque: almacén, perfiles y bases
# =============================================================================
def iniciar() -> None:
    if "almacen" in ss:
        return
    ss.almacen = Almacen(github=ConfigGitHub.desde_secrets(st.secrets))
    ss.mensajes = []
    try:
        ss.proveedores = ss.almacen.cargar_proveedores()
    except ErrorDeDatos as e:
        ss.proveedores = []
        ss.mensajes.append(("error", str(e)))
    if not ss.proveedores:
        ss.proveedores = [Proveedor("general", "Proveedor general")]
    ss.prov_id = ss.proveedores[0].id
    ss.conds = {}
    ss.lineas = {}
    ss.editor_v = {}

    try:
        cat, origen = ss.almacen.cargar_tabla(ARCH_LISTA)
    except ErrorDeDatos as e:
        cat, origen = None, ""
        ss.mensajes.append(("error", str(e)))
    poner_catalogo(cat if cat is not None and not cat.empty else catalogo_ejemplo(), ejemplo=cat is None or cat.empty, origen=origen)

    try:
        his, origen_h = ss.almacen.cargar_tabla(ARCH_HISTORIAL)
    except ErrorDeDatos as e:
        his, origen_h = None, ""
        ss.mensajes.append(("error", str(e)))
    poner_historial(his if his is not None and not his.empty else historial_ejemplo(), ejemplo=his is None or his.empty, origen=origen_h)


def poner_catalogo(df: pd.DataFrame, ejemplo: bool, origen: str = "") -> None:
    df = df.copy()
    df["CLAVE"] = df["DESCRIPCION"].map(fmt.normalizar)
    ss.catalogo = df
    ss.catalogo_ejemplo = ejemplo
    ss.catalogo_origen = origen
    ss.cat_idx = {r.CLAVE: r for r in df.itertuples(index=False)}
    ss.cat_opciones = df["DESCRIPCION"].tolist()


def poner_historial(df: pd.DataFrame, ejemplo: bool, origen: str = "") -> None:
    ss.historial = Historial(df)
    ss.historial_ejemplo = ejemplo
    ss.historial_origen = origen


def proveedor() -> Proveedor:
    return next((p for p in ss.proveedores if p.id == ss.prov_id), ss.proveedores[0])


def guardar_perfiles() -> None:
    try:
        ss.mensajes.append(("success", ss.almacen.guardar_proveedores(ss.proveedores)))
    except ErrorDeDatos as e:
        ss.mensajes.append(("warning", str(e)))


iniciar()

# =============================================================================
# Barra lateral: tasas, márgenes y bases de datos
# =============================================================================
with st.sidebar:
    st.header("Fecha y tasas")
    fecha = st.date_input("Fecha del pedido", value=date.today(), format="DD/MM/YYYY", key="fecha")
    bcv = st.number_input("Tasa BCV (Bs/$)", min_value=0.0, value=None, step=0.01, format="%.4f", key="bcv", placeholder="Ej. 210,50")
    interna = st.number_input("Tasa interna (Bs/$)", min_value=0.0, value=None, step=0.01, format="%.4f", key="interna", placeholder="Ej. 285,00")
    iva = st.number_input("IVA %", min_value=0.0, value=16.0, step=0.5, key="iva")
    c1, c2 = st.columns(2)
    m_min = c1.number_input("Margen mínimo %", min_value=0.0, value=17.0, step=0.5, key="m_min")
    m_obj = c2.number_input("Margen objetivo %", min_value=0.0, value=18.0, step=0.5, key="m_obj")
    iva_costo = st.toggle("Incluir el IVA en el costo", value=True, key="iva_costo")
    if bcv and interna:
        st.caption(f"BCV ÷ interna = **{fmt.num(bcv / interna, 4)}** · diferencial {fmt.pct(bcv / interna - 1)}")
    autor = st.text_input("Elaborado por", value="Ariana G. Romero Rodríguez", key="autor")

    st.divider()
    st.header("Bases de datos")
    st.caption(("🔄 Sincronizado con GitHub" if ss.almacen.sincroniza else "💾 Guardado en este equipo")
               + " · " + ("los datos persisten" if ss.almacen.sincroniza else "en Streamlit Cloud se borra al reiniciar (ver README)"))

    with st.expander("Lista de precios ACEVAL", expanded=ss.catalogo_ejemplo):
        if ss.catalogo_ejemplo:
            st.warning("Usando una lista de ejemplo. Carga tu Excel de precios.")
        else:
            st.success(f"{len(ss.catalogo):,} productos".replace(",", "."))
        archivo = st.file_uploader("Excel de la lista de precios", type=["xlsx", "xls", "xlsm", "csv"], key="up_lista",
                                   help="Listado maestro (hoja CONSOLIDADO) o un Excel con DESCRIPCION, PESO, P3 FERRE y P3 MCY.")
        if archivo is not None:
            try:
                lec = leer_lista_precios(archivo)
                ferre, mcy = lec.ferre, lec.mcy
                if lec.formato == "maestro":
                    ops = [""] + lec.tiendas
                    ferre = st.selectbox("Tienda FERRE", ops, index=ops.index(lec.ferre), key="sel_ferre")
                    mcy = st.selectbox("Tienda MCY", ops, index=ops.index(lec.mcy), key="sel_mcy")
                if lec.formato == "simple" or (ferre and mcy):
                    nuevo = lec.construir(ferre, mcy)
                    rs = resumen(nuevo)
                    st.write(f"**{rs['productos']}** productos · {rs['sin_peso']} sin peso · {rs['sin_p3']} sin P3 · "
                             f"{rs['p3_distinto']} con P3 FERRE ≠ MCY")
                    if st.button("Guardar lista", type="primary", key="btn_lista"):
                        try:
                            msg = ss.almacen.guardar_tabla(ARCH_LISTA, nuevo.drop(columns="CLAVE"), f"Lista de precios: {lec.archivo}")
                            ss.mensajes.append(("success", f"Lista guardada ({rs['productos']} productos). {msg}"))
                        except ErrorDeDatos as e:
                            ss.mensajes.append(("warning", str(e)))
                        poner_catalogo(nuevo, ejemplo=False)
                        st.rerun()
                else:
                    st.info("Elige cuál tienda es FERRE y cuál es MCY.")
            except ErrorDeDatos as e:
                st.error(str(e))

    with st.expander("Historial de compras", expanded=False):
        if ss.historial_ejemplo:
            st.warning("Usando un historial de ejemplo.")
        else:
            st.success(f"{len(ss.historial.df):,} compras".replace(",", "."))
        st.download_button("Descargar plantilla", plantilla_excel(), "plantilla_historial_compras.xlsx", key="dl_tpl")
        archivo_h = st.file_uploader("Excel del historial", type=["xlsx", "xls", "xlsm", "csv"], key="up_hist")
        if archivo_h is not None:
            try:
                lh = leer_historial(archivo_h)
                df = lh.datos
                claves = set(df["CLAVE"])
                coinciden = len(claves & set(ss.cat_idx)) if not ss.catalogo_ejemplo else None
                st.write(f"**{len(df)}** compras · {df['PROVEEDOR'].nunique()} proveedores · {len(claves)} productos"
                         + (f" · {coinciden} coinciden con la lista" if coinciden is not None else ""))
                if lh.filas_omitidas:
                    st.warning(f"Se omiten {len(lh.filas_omitidas)} filas incompletas: {', '.join(map(str, lh.filas_omitidas[:12]))}"
                               + ("…" if len(lh.filas_omitidas) > 12 else ""))
                if lh.opcionales_faltantes:
                    st.caption("Columnas opcionales que no vinieron: " + ", ".join(lh.opcionales_faltantes))
                if st.button("Guardar historial", type="primary", key="btn_hist", disabled=df.empty):
                    try:
                        msg = ss.almacen.guardar_tabla(ARCH_HISTORIAL, df.drop(columns="CLAVE"), f"Historial: {lh.archivo}")
                        ss.mensajes.append(("success", f"Historial guardado ({len(df)} compras). {msg}"))
                    except ErrorDeDatos as e:
                        ss.mensajes.append(("warning", str(e)))
                    poner_historial(df, ejemplo=False)
                    st.rerun()
            except ErrorDeDatos as e:
                st.error(str(e))
    st.caption(f"Versión {__version__}")

# =============================================================================
# Encabezado y mensajes
# =============================================================================
st.title("Costeo de Compras")
st.caption("Cotización del proveedor → lo que realmente pagamos en $ interno → costo por pieza y por kilo → comparación con P3 de FERRE / MCY.")
for tipo, texto in ss.mensajes:
    getattr(st, tipo)(md(texto))
ss.mensajes = []

# =============================================================================
# Proveedor y forma de pago
# =============================================================================
st.subheader("1 · Proveedor y forma de pago")
prov = proveedor()
ids = [p.id for p in ss.proveedores]
if ss.get("sel_prov") not in ids:
    ss.sel_prov = prov.id


# Las acciones que cambian widgets van en callbacks: corren antes de dibujar la página.
def cb_cambiar_proveedor() -> None:
    ss.prov_id = ss.sel_prov


def cb_crear_proveedor() -> None:
    nombre = ss.get("nombre_prov", "").strip().upper()
    if not nombre:
        return
    p = Proveedor(f"p_{uuid.uuid4().hex[:8]}", nombre, Condiciones.desde_dict(proveedor().condiciones.a_dict()))
    ss.proveedores.append(p)
    ss.prov_id = ss.sel_prov = p.id
    ss.nombre_prov = ""
    guardar_perfiles()


def cb_renombrar_proveedor() -> None:
    nombre = ss.get("nombre_prov", "").strip().upper()
    if nombre:
        proveedor().nombre = nombre
        ss.nombre_prov = ""
        guardar_perfiles()


def cb_eliminar_proveedor() -> None:
    actual = proveedor()
    if len(ss.proveedores) < 2:
        return
    ss.proveedores = [p for p in ss.proveedores if p.id != actual.id]
    ss.conds.pop(actual.id, None)
    ss.lineas.pop(actual.id, None)
    ss.prov_id = ss.sel_prov = ss.proveedores[0].id
    guardar_perfiles()


c_sel, c_nuevo, c_borrar = st.columns([3, 1, 1], vertical_alignment="bottom")
c_sel.selectbox("Proveedor", ids, format_func=lambda i: next(p.nombre for p in ss.proveedores if p.id == i),
                key="sel_prov", on_change=cb_cambiar_proveedor)

with c_nuevo.popover("Nuevo / renombrar", width="stretch"):
    st.text_input("Nombre", key="nombre_prov")
    hay_nombre = bool(ss.get("nombre_prov", "").strip())
    st.button("Crear proveedor", disabled=not hay_nombre, key="btn_crear", on_click=cb_crear_proveedor,
              help="Se crea con las mismas condiciones del proveedor actual; luego las ajustas.")
    st.button(f"Renombrar {prov.nombre}", disabled=not hay_nombre, key="btn_renombrar", on_click=cb_renombrar_proveedor)

with c_borrar.popover("Eliminar", width="stretch"):
    st.write(f"¿Eliminar a **{prov.nombre}** y su perfil?")
    st.button("Sí, eliminar", type="primary", disabled=len(ss.proveedores) < 2, key="btn_borrar", on_click=cb_eliminar_proveedor)
    if len(ss.proveedores) < 2:
        st.caption("Debe quedar al menos un proveedor.")

pid = prov.id
k = lambda campo: f"c_{pid}_{campo}"  # noqa: E731 - clave de widget por proveedor


def valores_widgets(c: Condiciones) -> dict:
    """Condiciones → valores en el formato que usan los widgets."""
    return {
        "moneda": c.moneda, "precio_por": c.precio_por, "iva_incluido": c.iva_incluido, "iva_base": c.iva_base,
        "pago": c.pago, "pago_valor": float(c.pago_valor), "flete": float(c.flete), "flete_moneda": c.flete_moneda,
        "toneladas": float(c.toneladas), "flete_carga_real": c.flete_carga_real,
        "descuentos": "; ".join(fmt.num(d).rstrip("0").rstrip(",") for d in c.descuentos),
    }


def cargar_widgets(c: Condiciones) -> None:
    """Pone todas las condiciones en los widgets de este proveedor (pisa lo que haya)."""
    for campo, v in valores_widgets(c).items():
        ss[k(campo)] = v


# Streamlit descarta el estado de un widget cuando deja de dibujarse (por ejemplo el
# "% pagado en dólares" si la forma de pago no lo usa, o todos al cambiar de proveedor):
# la clave desaparece o, al volver a dibujarse, el widget vuelve a su valor por defecto.
# Solución documentada: reasignar cada clave en cada corrida (así queda como valor
# propio y no como estado de widget) y restaurar las que falten desde lo último guardado.
GUARDADAS = valores_widgets(ss.conds.get(pid, prov.condiciones))
for _campo, _valor in GUARDADAS.items():
    ss[k(_campo)] = ss[k(_campo)] if k(_campo) in ss else _valor


def valor(campo: str):
    """Valor actual del campo; si su widget no se dibujó en esta corrida, el último guardado."""
    return ss.get(k(campo), GUARDADAS[campo])


def leer_descuentos(texto: str) -> list[float]:
    vals = []
    for parte in str(texto).replace("+", ";").split(";"):
        parte = parte.strip().replace("%", "")
        if parte:
            try:
                vals.append(float(parte.replace(",", ".")))
            except ValueError:
                st.error(f"Descuento no válido: «{parte}». Escribe números separados por punto y coma, por ejemplo: 3; 2")
    return vals


g1, g2, g3, g4 = st.columns(4)
g1.selectbox("Moneda de la cotización", list(MONEDAS), format_func=MONEDAS.get, key=k("moneda"))
g2.selectbox("Precio cotizado por", list(PRECIO_POR), format_func=PRECIO_POR.get, key=k("precio_por"))
g3.selectbox("¿El precio incluye IVA?", [False, True], format_func=lambda v: "Sí, viene con IVA" if v else "No, viene sin IVA", key=k("iva_incluido"))
g4.selectbox("IVA calculado sobre", list(IVA_BASE), format_func=IVA_BASE.get, key=k("iva_base"))

if valor("moneda") == "usd":
    h1, h2 = st.columns(2)
    h1.selectbox("Cómo se paga la base", list(FORMAS_PAGO), format_func=FORMAS_PAGO.get, key=k("pago"))
    if valor("pago") == "pct":
        h2.number_input("% pagado en dólares", min_value=0.0, max_value=100.0, step=5.0, key=k("pago_valor"))
    elif valor("pago") == "monto":
        h2.number_input("Monto pagado en dólares ($)", min_value=0.0, step=500.0, key=k("pago_valor"),
                        help="Ejemplo COMPLEJO: si la gandola cuesta 31.500 y 13.000 se pagan en $, escribe 13000. El resto se paga en Bs a BCV.")
    st.caption(md("El IVA de una cotización en dólares se paga siempre en Bs a tasa BCV: para el costo se lleva a $ con × BCV ÷ interna."))
else:
    st.caption("Cotización en bolívares: la base y el IVA se dividen entre la tasa interna.")

f1, f2, f3, f4 = st.columns(4)
f1.number_input("Flete por gandola", min_value=0.0, step=50.0, key=k("flete"))
f2.selectbox("Moneda del flete", list(MONEDAS_FLETE), format_func=MONEDAS_FLETE.get, key=k("flete_moneda"))
f3.number_input("Toneladas por gandola", min_value=1.0, step=1.0, key=k("toneladas"))
f4.text_input("Descuentos sobre la base %", key=k("descuentos"), placeholder="Ej. 3; 2", help="En cascada: 3; 2 = 3% y luego 2% sobre lo que queda.")
st.toggle("Repartir el flete sobre los kilos reales del pedido (si no llena la gandola)", key=k("flete_carga_real"))

try:
    cond = Condiciones(
        moneda=valor("moneda"), precio_por=valor("precio_por"), iva_incluido=valor("iva_incluido"),
        iva_base=valor("iva_base"), pago=valor("pago"), pago_valor=valor("pago_valor"),
        flete=valor("flete"), flete_moneda=valor("flete_moneda"), toneladas=valor("toneladas"),
        flete_carga_real=valor("flete_carga_real"), descuentos=leer_descuentos(valor("descuentos")),
    )
except ErrorDeDatos as e:
    st.error(str(e))
    st.stop()
ss.conds[pid] = cond

def cb_guardar_perfil() -> None:
    p = proveedor()
    p.condiciones = Condiciones.desde_dict(ss.conds[p.id].a_dict())
    guardar_perfiles()


def cb_volver_perfil() -> None:
    p = proveedor()
    ss.conds.pop(p.id, None)
    cargar_widgets(p.condiciones)


if cond.clave() != prov.condiciones.clave():
    w1, w2, w3 = st.columns([4, 1, 1], vertical_alignment="center")
    w1.warning(f"Condiciones cambiadas **solo para esta cotización**. El perfil de {prov.nombre} sigue igual.")
    w2.button("Guardar en el perfil", type="primary", width="stretch", key="btn_guardar_perfil", on_click=cb_guardar_perfil)
    w3.button("Volver al perfil", width="stretch", key="btn_volver_perfil", on_click=cb_volver_perfil)
else:
    st.caption(f"Usando las condiciones guardadas de **{prov.nombre}**. Si cambias algo, aplica solo a esta cotización hasta que lo guardes en el perfil.")

# =============================================================================
# Productos
# =============================================================================
st.subheader("2 · Productos del pedido")
if pid not in ss.lineas:
    ss.lineas[pid] = pd.DataFrame(columns=COLS_LINEAS).astype({c: "float" for c in COLS_LINEAS[1:]} | {"Producto": "object"})
    ss.editor_v[pid] = 0


def datos_catalogo(desc: str):
    return ss.cat_idx.get(fmt.normalizar(desc))


def reemplazar_lineas(df: pd.DataFrame) -> None:
    ss.lineas[pid] = df.reset_index(drop=True)
    ss.editor_v[pid] = ss.editor_v.get(pid, 0) + 1


b1, b2, b3, b4 = st.columns([4, 1.2, 1.2, 1], vertical_alignment="bottom")
buscado = b1.selectbox("Buscar en la lista de precios", ss.cat_opciones, index=None, key=f"busca_{pid}_{ss.editor_v[pid]}",
                       placeholder="Escribe parte del nombre, por ejemplo: cab 1/2")
cant_n = b2.number_input("Cantidad de piezas", min_value=0.0, value=None, step=1.0, key=f"cant_{pid}_{ss.editor_v[pid]}")
precio_n = b3.number_input("Precio proveedor", min_value=0.0, value=None, step=0.01, format="%.4f", key=f"precio_{pid}_{ss.editor_v[pid]}")
if buscado:
    r = datos_catalogo(buscado)
    st.caption(f"{buscado}: {fmt.num(r.PESO)} kg · P3 FERRE {fmt.num(r.P3_FERRE)} · MCY {fmt.num(r.P3_MCY)}")

if b4.button("Agregar", type="primary", disabled=not buscado, width="stretch", key="btn_agregar"):
    r = datos_catalogo(buscado)
    fila = {"Producto": r.DESCRIPCION, "Cantidad": cant_n, "Precio": precio_n, "Desc. extra %": 0.0,
            "Peso kg": r.PESO, "P3 FERRE": r.P3_FERRE, "P3 MCY": r.P3_MCY}
    base = ss.get(f"_ultimo_editado_{pid}", ss.lineas[pid])
    reemplazar_lineas(pd.concat([base, pd.DataFrame([fila])], ignore_index=True))
    st.rerun()

etiqueta_precio = f"Precio {'Bs' if cond.moneda == 'bs' else '$'} {'c/IVA' if cond.iva_incluido else 's/IVA'} / {PRECIO_POR[cond.precio_por].lower()}"
editado = st.data_editor(
    ss.lineas[pid],
    key=f"ed_{pid}_{ss.editor_v[pid]}",
    num_rows="dynamic",
    width="stretch",
    hide_index=True,
    column_config={
        "Producto": st.column_config.TextColumn("Producto", width="large", required=True),
        "Cantidad": st.column_config.NumberColumn("Cant. piezas", min_value=0, format="%.2f"),
        "Precio": st.column_config.NumberColumn(etiqueta_precio, min_value=0, format="%.4f"),
        "Desc. extra %": st.column_config.NumberColumn("Desc. extra %", min_value=0, max_value=100, format="%.2f"),
        "Peso kg": st.column_config.NumberColumn("Peso pieza kg", min_value=0, format="%.4f"),
        "P3 FERRE": st.column_config.NumberColumn("P3 FERRE $", min_value=0, format="%.4f"),
        "P3 MCY": st.column_config.NumberColumn("P3 MCY $", min_value=0, format="%.4f"),
    },
)
ss[f"_ultimo_editado_{pid}"] = editado

# Completar peso y P3 vacíos desde la lista (sin pisar lo escrito a mano)
completados = 0
lineas: list[Linea] = []
for fila in editado.itertuples(index=False):
    desc = str(fila.Producto or "").strip()
    if not desc or desc.lower() == "nan":
        continue
    peso, p3f, p3m = fila[4], fila[5], fila[6]
    r = datos_catalogo(desc)
    if r is not None:
        if not (peso and peso > 0):
            peso, completados = r.PESO, completados + 1
        if not (p3f and p3f > 0):
            p3f = r.P3_FERRE
        if not (p3m and p3m > 0):
            p3m = r.P3_MCY
    lineas.append(Linea(desc, fila.Cantidad if pd.notna(fila.Cantidad) else float("nan"),
                        fila.Precio if pd.notna(fila.Precio) else float("nan"),
                        peso if pd.notna(peso) else float("nan"),
                        p3f if pd.notna(p3f) else 0.0, p3m if pd.notna(p3m) else 0.0,
                        fila[3] if pd.notna(fila[3]) else 0.0))

a1, a2, a3 = st.columns([2, 2, 3])
if a1.button("Actualizar peso y P3 desde la lista", width="stretch", key="btn_refrescar"):
    df = editado.copy()
    for i, desc in df["Producto"].items():
        r = datos_catalogo(str(desc or ""))
        if r is not None:
            df.loc[i, ["Peso kg", "P3 FERRE", "P3 MCY"]] = [r.PESO, r.P3_FERRE, r.P3_MCY]
    reemplazar_lineas(df)
    st.rerun()
if a2.button("Vaciar productos", width="stretch", key="btn_vaciar"):
    reemplazar_lineas(ss.lineas[pid].iloc[0:0])
    st.rerun()
a3.caption("Puedes pegar filas copiadas de Excel directo en la tabla. Si el producto está en la lista, el peso y el P3 vacíos se completan solos."
           + (f" Se completaron {completados} pesos desde la lista." if completados else ""))

def cb_ejemplo() -> None:
    ej = [('CABILLA 1/2" X 12 MTS', 1400, 11.20), ('CABILLA 3/8" X 12 MTS', 1600, 6.30), ('CABILLA 5/8" X 12 MTS', 200, 17.60)]
    filas = []
    for d, c, pr in ej:
        r = datos_catalogo(d)
        if r is not None:
            filas.append({"Producto": d, "Cantidad": c, "Precio": pr, "Desc. extra %": 0.0,
                          "Peso kg": r.PESO, "P3 FERRE": r.P3_FERRE, "P3 MCY": r.P3_MCY})
    reemplazar_lineas(pd.DataFrame(filas, columns=COLS_LINEAS))
    if not ss.get("bcv"):
        ss.bcv, ss.interna = 210.5, 285.0


if ss.catalogo_ejemplo and not lineas:
    st.button("Cargar un ejemplo para probar (tasas y precios de ejemplo)", key="btn_ejemplo", on_click=cb_ejemplo)

# =============================================================================
# Resultado
# =============================================================================
st.subheader("3 · Resultado")
params = Parametros(fecha=fecha, tasa_bcv=bcv or 0.0, tasa_interna=interna or 0.0, iva=iva,
                    margen_min=m_min, margen_obj=m_obj, iva_en_costo=iva_costo)
if not lineas:
    st.info("Agrega productos para ver el costeo.")
    st.stop()

res = calcular(params, cond, lineas)
for e in res.errores:
    st.error(e)
if res.errores:
    st.stop()
for a in res.avisos:
    st.warning(md(a))

mon = "Bs" if cond.moneda == "bs" else "$"
cnt = res.conteo()
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("🔴 Subir", cnt["SUBIR"])
m2.metric("🟡 Revisar", cnt["REVISAR"])
m3.metric("🟢 Mantener", cnt["MANTENER"])
m4.metric(f"Kilos totales · {fmt.num(res.totales.kg / (cond.toneladas * 1000))} gandolas", fmt.num(res.totales.kg))
m5.metric("Gasto total $ interno", fmt.num(res.plan.gasto_int),
          help=f"{fmt.num(res.plan.gasto_int / res.totales.kg, 4)} $ por kilo" if res.totales.kg else None)

t, pl = res.totales, res.plan
k1, k2 = st.columns(2)
with k1.container(border=True):
    st.markdown("**Cotización del proveedor**")
    st.markdown(md(
        f"| Concepto | Monto |\n|---|---:|\n"
        f"| Total sin IVA | {mon} {fmt.num(t.sin_iva)} |\n"
        f"| IVA {'(sobre el 10%)' if cond.iva_base == '10' else ''} | {mon} {fmt.num(t.iva)} |\n"
        f"| **Total con IVA** | **{mon} {fmt.num(t.con_iva)}** |\n"
        f"| Condiciones | {describir_iva(cond, iva)} |\n"
        + (f"| Descuentos | {' + '.join(fmt.num(x) + '%' for x in cond.descuentos)} |\n" if cond.descuentos else "")
    ))
with k2.container(border=True):
    st.markdown("**Cómo se paga**")
    if cond.moneda == "usd":
        st.markdown(md(
            f"| Concepto | Monto |\n|---|---:|\n"
            f"| Base en dólares | $ {fmt.num(pl.usd)} |\n"
            f"| Base en Bs a BCV | Bs {fmt.num(pl.bs_base)} <br><small>$ {fmt.num(pl.usd_base_en_bs)} × {fmt.num(params.tasa_bcv)}</small> |\n"
            f"| IVA en Bs a BCV | Bs {fmt.num(pl.bs_iva)} <br><small>$ {fmt.num(pl.usd_iva)} × {fmt.num(params.tasa_bcv)}</small> |\n"
            f"| **Total en bolívares** | **Bs {fmt.num(pl.bs_total)}** |\n"
            f"| Flete | $ int. {fmt.num(pl.flete_int)} |\n"
            f"| **Gasto total en $ interno** | **$ {fmt.num(pl.gasto_int)}** |\n"), unsafe_allow_html=True)
        st.caption(md(f"{describir_pago(cond)}. Los Bs se llevan a $ interno dividiendo entre {fmt.num(params.tasa_interna)}."))
    else:
        st.markdown(md(
            f"| Concepto | Monto |\n|---|---:|\n| Base | Bs {fmt.num(pl.bs_base)} |\n| IVA | Bs {fmt.num(pl.bs_iva)} |\n"
            f"| **Total en bolívares** | **Bs {fmt.num(pl.bs_total)}** |\n| Flete | $ int. {fmt.num(pl.flete_int)} |\n"
            f"| **Gasto total en $ interno** | **$ {fmt.num(pl.gasto_int)}** |\n"))
        st.caption(f"Bolívares ÷ tasa interna {fmt.num(params.tasa_interna)}.")

df_res = tabla(res, params, prov, cond, ss.historial)
pct_cols = [c for c in df_res.columns if c.startswith("Dif.")]
num_cols = [c for c in df_res.columns if df_res[c].dtype.kind in "fi" and c not in pct_cols]
estilo = (
    df_res.style
    .format(precision=4, subset=num_cols, na_rep="—", thousands=".", decimal=",")
    .format(lambda v: fmt.pct(v), subset=pct_cols)
    .map(lambda v: COLORES_ACCION.get(v, ""), subset=["Acción"])
    .map(lambda v: "color:#B91C1C" if isinstance(v, float) and v < 0 else "color:#15803D", subset=pct_cols)
)
st.dataframe(estilo, width="stretch", hide_index=True, height=min(80 + 36 * len(df_res), 520))

# --- detalle de un producto -----------------------------------------------
st.markdown("##### Detalle por producto")
nombres = [r.linea.descripcion for r in res.lineas]
sel = st.selectbox("Producto", range(len(nombres)), format_func=lambda i: nombres[i], key="detalle", label_visibility="collapsed")
r = res.lineas[sel]
d1, d2 = st.columns(2)
with d1.container(border=True):
    if not r.tiene_costo:
        st.error(f"{r.linea.descripcion}: {r.error}")
    else:
        ln = r.linea
        descs = [*cond.descuentos, *([ln.desc_extra] if ln.desc_extra else [])]
        if res.porcion_divisa is None:
            base_txt = f"÷ interna {fmt.num(params.tasa_interna)}"
        elif res.porcion_divisa == 1:
            base_txt = "pagada en $ (× 1)"
        elif res.porcion_divisa == 0:
            base_txt = "Bs a BCV (× BCV ÷ interna)"
        else:
            base_txt = f"{fmt.num(res.porcion_divisa * 100, 1)}% en $ + {fmt.num((1 - res.porcion_divisa) * 100, 1)}% Bs a BCV"
        pasos = [
            (f"Precio cotizado por {PRECIO_POR[cond.precio_por].lower()} ({mon})", fmt.num(ln.precio, 4)),
            ("Precio por pieza", fmt.num(r.precio_pieza, 4)),
            *([(f"Se quita el IVA (÷ {fmt.num(1 + res.tasa_iva_efectiva, 4)})", fmt.num(r.lista_sin_iva, 4))] if cond.iva_incluido else []),
            (f"Descuentos sobre la base: {' → '.join(fmt.num(x) + '%' for x in descs) or 'ninguno'}", fmt.num(r.pieza_sin_iva, 4)),
            (f"IVA {iva:g}%{' sobre el 10%' if cond.iva_base == '10' else ''}", "+ " + fmt.num(r.iva_pieza, 4)),
            (f"**Pieza con IVA ({mon})**", f"**{fmt.num(r.pieza_con_iva, 4)}**"),
            (f"Base a $ interno: {base_txt} (× {fmt.num(res.factor_base, 4)})", fmt.num(r.base_int, 4)),
            (f"IVA a $ interno: {'÷ interna' if cond.moneda == 'bs' else 'Bs a BCV'} (× {fmt.num(res.factor_iva, 4)})"
             + ("" if iva_costo else " · no se suma"), ("+ " if iva_costo else "") + fmt.num(r.iva_int, 4)),
            (f"Flete: {fmt.num(res.flete_kg, 4)} $/kg × {fmt.num(ln.peso)} kg", "+ " + fmt.num(r.flete_pieza, 4)),
            ("**Costo por pieza ($ interno)**", f"**{fmt.num(r.costo_pieza, 4)}**"),
            ("**Costo por kilo**", f"**{fmt.num(r.costo_kg, 4)}**"),
            (f"Costo × {1 + m_min / 100:g} · por kilo", f"{fmt.num(r.costo_min, 4)} · {fmt.num(r.kg_min, 4)}"),
            (f"Costo × {1 + m_obj / 100:g} · por kilo", f"{fmt.num(r.costo_obj, 4)} · {fmt.num(r.kg_obj, 4)}"),
            ("P3 FERRE · MCY", f"{fmt.num(ln.p3_ferre, 4)} · {fmt.num(ln.p3_mcy, 4)}"),
            (f"**Acción: {r.accion}**", "—" if r.accion == "MANTENER" else f"P3 sugerido **{fmt.num(r.p3_sugerido, 4)}**"),
        ]
        st.markdown(md("| Paso | Valor |\n|---|---:|\n" + "\n".join(f"| {a} | {b} |" for a, b in pasos)))
with d2.container(border=True):
    st.markdown("**Historial de compra**" + (" · _ejemplo_" if ss.historial_ejemplo else ""))
    ult = ss.historial.ultima(r.linea.descripcion)
    if not ult:
        st.caption("No hay compras registradas de este producto.")
    else:
        datos = [("Fecha", fmt.fecha(ult["FECHA"])), ("Proveedor", ult["PROVEEDOR"]),
                 ("Precio", f"{fmt.num(ult['PRECIO'], 4)} {ult.get('MONEDA') or ''}")]
        if fmt.es_numero(ult.get("COSTO_KG")):
            cambio = f" (hoy {fmt.pct(r.costo_kg / ult['COSTO_KG'] - 1)})" if r.tiene_costo else ""
            datos.append(("Costo kg", fmt.num(ult["COSTO_KG"], 4) + cambio))
        for etiqueta, col in (("Cantidad", "CANTIDAD"), ("Tasa", "TASA"), ("Descuento %", "DESCUENTO")):
            if fmt.es_numero(ult.get(col)) and ult[col]:
                datos.append((etiqueta, fmt.num(ult[col])))
        for etiqueta, col in (("Factura / OC", "FACTURA"), ("Condiciones", "CONDICIONES"), ("RIF", "RIF"),
                              ("Contacto", "CONTACTO"), ("Nota", "OBSERVACION")):
            v = ult.get(col)
            if isinstance(v, str) and v.strip():
                datos.append((etiqueta, v))
        st.markdown(md("**Última compra**\n\n| Dato | Valor |\n|---|---:|\n" + "\n".join(f"| {a} | {b} |" for a, b in datos)))
        pp = ss.historial.por_proveedor(r.linea.descripcion)
        if len(ss.historial.compras(r.linea.descripcion)) > 1:
            st.markdown("**Último precio de cada proveedor**")
            vista = pp[["PROVEEDOR", "FECHA", "PRECIO", "COSTO_KG", "CONDICIONES"]].copy()
            vista["FECHA"] = vista["FECHA"].map(fmt.fecha)
            vista["PRECIO"] = vista["PRECIO"].map(lambda v: fmt.num(v, 4))
            vista["COSTO_KG"] = vista["COSTO_KG"].map(lambda v: fmt.num(v, 4))
            st.dataframe(vista.rename(columns={"PROVEEDOR": "Proveedor", "FECHA": "Fecha", "PRECIO": "Precio", "COSTO_KG": "Costo kg", "CONDICIONES": "Condiciones"}),
                         hide_index=True, width="stretch")

# --- exportes ---------------------------------------------------------------
st.markdown("##### Compartir")
nombre_base = f"costeo_{fmt.slug(prov.nombre)}_{params.fecha.isoformat()}"
try:
    png = imagen(res, params, prov, cond, ss.historial, autor)
    xls = excel(res, params, prov, cond, ss.historial)
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudieron generar los archivos: {e}")
    st.stop()
e1, e2 = st.columns(2)
e1.download_button("📱 Descargar imagen para WhatsApp", png, f"{nombre_base}.png", "image/png", type="primary", width="stretch")
e2.download_button("📊 Descargar Excel", xls, f"{nombre_base}.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
with st.expander("Vista previa de la imagen"):
    st.image(png, width=420)
