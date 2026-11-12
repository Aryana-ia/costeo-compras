"""Exportes del resultado: tabla, Excel e imagen PNG para WhatsApp."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from . import formato as fmt
from .calculo import describir_iva, describir_pago, describir_tasas
from .modelos import Condiciones, Parametros, Proveedor, Resultado

FUENTES = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def tabla(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones, historial=None) -> pd.DataFrame:
    """Una fila por producto con todas las columnas del costeo (valores numéricos)."""
    filas = []
    mon = "Bs" if cond.moneda == "bs" else "$"
    for r in res.lineas:
        ln = r.linea
        ult = historial.ultima(ln.descripcion) if historial is not None else None
        filas.append({
            "Producto": ln.descripcion,
            "Cantidad": ln.cantidad,
            "Peso kg": ln.peso,
            "Kg total": r.kg_total,
            f"Precio cotizado ({mon})": ln.precio,
            f"Lista s/IVA ({mon})": r.lista_sin_iva,
            f"Pieza s/IVA ({mon})": r.pieza_sin_iva,
            f"IVA pieza ({mon})": r.iva_pieza,
            f"Pieza c/IVA ({mon})": r.pieza_con_iva,
            f"Kg s/IVA ({mon})": r.kg_sin_iva,
            f"Kg c/IVA ({mon})": r.kg_con_iva,
            f"Total s/IVA ({mon})": r.total_sin_iva,
            f"Total IVA ({mon})": r.total_iva,
            f"Total c/IVA ({mon})": r.total_con_iva,
            "Gandolas": ln.gandolas if cond.pago == "monto_gandola" else None,
            "Base pagada en $ (línea)": r.usd_linea if cond.moneda == "usd" else None,
            "Base $ int.": r.base_int,
            "IVA $ int.": r.iva_int,
            "Flete $ int.": r.flete_pieza,
            "IGTF $": r.igtf_pieza,
            "Costo pieza $": r.costo_pieza,
            "Costo kg $": r.costo_kg,
            f"Pieza +{p.margen_min:g}%": r.costo_min,
            f"Pieza +{p.margen_obj:g}%": r.costo_obj,
            f"Kg +{p.margen_min:g}%": r.kg_min,
            f"Kg +{p.margen_obj:g}%": r.kg_obj,
            "P3 FERRE": ln.p3_ferre or None,
            "P3 MCY": ln.p3_mcy or None,
            "Kilo P3": r.kilo_p3,
            f"Dif. vs {p.margen_min:g}%": r.dif_min,
            f"Dif. vs {p.margen_obj:g}%": r.dif_obj,
            "Acción": r.accion if r.tiene_costo else "ERROR",
            "P3 sugerido": None if r.accion == "MANTENER" or not r.tiene_costo else r.p3_sugerido,
            "Observación": r.error or ("P3 MCY distinto de FERRE" if r.mcy_distinto else ""),
            "Últ. compra fecha": fmt.fecha(ult["FECHA"]) if ult else "",
            "Últ. compra proveedor": ult["PROVEEDOR"] if ult else "",
            "Últ. compra precio": ult["PRECIO"] if ult else None,
            "Últ. compra costo kg": ult["COSTO_KG"] if ult else None,
        })
    return pd.DataFrame(filas)


def resumen_pago(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones) -> pd.DataFrame:
    t, pl = res.totales, res.plan
    mon = "Bs" if cond.moneda == "bs" else "$"
    filas = [
        ("Proveedor", prov.nombre),
        ("Fecha del pedido", fmt.fecha(p.fecha)),
        ("Tasa BCV $", p.tasa_bcv),
        ("Tasa BCV €", p.tasa_bcv_eur if describir_tasas(cond) else None),
        ("Tasa interna", p.tasa_interna),
        ("Forma de pago", describir_pago(cond)),
        ("IVA", describir_iva(cond, p.iva)),
        ("IVA incluido en el costo", "Sí" if p.iva_en_costo else "No"),
        ("", ""),
        ("Piezas", t.piezas),
        ("Kilos totales", t.kg),
        (f"Total sin IVA ({mon})", t.sin_iva),
        (f"IVA ({mon})", t.iva),
        (f"Total con IVA ({mon})", t.con_iva),
        ("", ""),
        ("Base pagada en $", pl.usd),
        ("Base pagada en Bs", pl.bs_base),
        ("IVA pagado en Bs", pl.bs_iva),
        (f"  · Retención IVA {pl.retencion_pct:g}% (al SENIAT) Bs", pl.bs_iva_retenido if pl.retencion_pct else None),
        ("      en $ a tasa BCV", pl.en_dolares(pl.bs_iva_retenido)[0] if pl.retencion_pct else None),
        ("      en $ interno", pl.en_dolares(pl.bs_iva_retenido)[1] if pl.retencion_pct else None),
        ("  · IVA al proveedor Bs", pl.bs_iva_proveedor if pl.retencion_pct else None),
        ("      en $ a tasa BCV", pl.en_dolares(pl.bs_iva_proveedor)[0] if pl.retencion_pct else None),
        ("      en $ interno", pl.en_dolares(pl.bs_iva_proveedor)[1] if pl.retencion_pct else None),
        ("Al proveedor en $", pl.usd if pl.retencion_pct else None),
        ("Al proveedor en Bs", pl.bs_al_proveedor if pl.retencion_pct else None),
        ("      en $ a tasa BCV", pl.en_dolares(pl.bs_al_proveedor)[0] if pl.retencion_pct else None),
        ("      en $ interno", pl.en_dolares(pl.bs_al_proveedor)[1] if pl.retencion_pct else None),
        ("Total en Bs", pl.bs_total),
        ("Flete ($ interno)", pl.flete_int),
        ("IGTF ($)", pl.igtf),
        ("Gasto total ($ interno)", pl.gasto_int),
        ("Gasto por kilo ($ interno)", pl.gasto_int / t.kg if t.kg else None),
    ]
    filas = [f for f in filas if f[1] is not None]  # se omiten las filas que no aplican
    return pd.DataFrame(filas, columns=["Concepto", "Valor"])


def excel(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones, historial=None) -> bytes:
    df = tabla(res, p, prov, cond, historial)
    rp = resumen_pago(res, p, prov, cond)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        libro = w.book
        f_num = libro.add_format({"num_format": "#,##0.0000"})
        f_pct = libro.add_format({"num_format": "+0.0%;-0.0%;0.0%"})
        f_head = libro.add_format({"bold": True, "bg_color": "#151B26", "font_color": "#FFFFFF", "text_wrap": True, "valign": "vcenter"})
        colores = {"SUBIR": ("#FBE4E4", "#B91C1C"), "REVISAR": ("#FBF1D6", "#A16207"), "MANTENER": ("#E3F4E8", "#15803D"), "ERROR": ("#B91C1C", "#FFFFFF")}

        df.to_excel(w, index=False, sheet_name="Costeo")
        hoja = w.sheets["Costeo"]
        hoja.freeze_panes(1, 1)
        hoja.set_row(0, 34)
        for k, col in enumerate(df.columns):
            hoja.write(0, k, col, f_head)
            if col == "Producto":
                hoja.set_column(k, k, 42)
            elif col.startswith("Dif."):
                hoja.set_column(k, k, 12, f_pct)
            elif df[col].dtype.kind in "fi":
                hoja.set_column(k, k, 13, f_num)
            else:
                hoja.set_column(k, k, 16)
        k_acc = list(df.columns).index("Acción")
        for accion, (fondo, letra) in colores.items():
            hoja.conditional_format(1, k_acc, len(df), k_acc, {
                "type": "cell", "criteria": "==", "value": f'"{accion}"',
                "format": libro.add_format({"bg_color": fondo, "font_color": letra, "bold": True}),
            })

        rp.to_excel(w, index=False, sheet_name="Resumen y pago")
        h2 = w.sheets["Resumen y pago"]
        h2.set_column(0, 0, 30)
        h2.set_column(1, 1, 30, libro.add_format({"num_format": "#,##0.00"}))
        for k, col in enumerate(rp.columns):
            h2.write(0, k, col, f_head)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Imagen para WhatsApp
# ---------------------------------------------------------------------------
C = {
    "bg": "#F3F4F6", "panel": "#FFFFFF", "ink": "#151B26", "mut": "#5B6474", "line": "#D9DDE4", "head": "#151B26",
    "acc": "#7AA2FF", "head2": "#C9D1DE", "head3": "#8B95A7",
    "accent": "#1D4ED8", "caja": "#F3F5F9", "resalte": "#E3EAFC",
    "SUBIR": ("#FBE4E4", "#B91C1C"), "REVISAR": ("#FBF1D6", "#A16207"),
    "MANTENER": ("#E3F4E8", "#15803D"), "ERROR": ("#B91C1C", "#FFFFFF"),
}


def _fuente(nombre: str, tam: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FUENTES / nombre), tam)
    except OSError:
        return ImageFont.load_default(size=tam)


def _envolver(d: ImageDraw.ImageDraw, texto: str, fuente, ancho: int) -> list[str]:
    lineas, cur = [], ""
    for palabra in str(texto).split():
        prueba = f"{cur} {palabra}".strip()
        if d.textlength(prueba, font=fuente) > ancho and cur:
            lineas.append(cur)
            cur = palabra
        else:
            cur = prueba
    if cur:
        lineas.append(cur)
    return lineas or [""]


def _texto_ajustado(d: ImageDraw.ImageDraw, xy, texto: str, ancho: int, tam: int, color: str, nombre="DejaVuSansMono.ttf") -> None:
    """Dibuja ``texto`` reduciendo la letra hasta que quepa en ``ancho``."""
    f = _fuente(nombre, tam)
    while d.textlength(texto, font=f) > ancho and tam > 14:
        tam -= 2
        f = _fuente(nombre, tam)
    d.text(xy, texto, font=f, fill=color)


# Alturas de las secciones de la tarjeta de producto (px)
H_TITULO, H_PROV, H_CAJAS, H_TABLA, H_FRANJA, H_HIST = 38, 112, 132, 168, 70, 40


def _alto_producto(r, n_lineas: int, ult) -> int:
    if not r.tiene_costo:
        return 30 + n_lineas * H_TITULO + 60
    return 26 + n_lineas * H_TITULO + 12 + H_PROV + H_CAJAS + H_TABLA + H_FRANJA + (H_HIST if ult else 0) + 14


def _tarjeta_producto(d, x0, y0, ancho, alto, r, nl, ult, p: Parametros, mon: str, F) -> None:
    """Una tarjeta por producto, en cinco bloques:
    proveedor → nuestro costo / actual FERRE-MCY → sugeridos 17 % y 18 % → recomendación → última compra."""
    d.rounded_rectangle([x0, y0, x0 + ancho, y0 + alto], 14, fill=C["panel"], outline=C["line"], width=2)
    x, w = x0 + 28, ancho - 56
    y = y0 + 26
    for texto in nl:
        d.text((x, y), texto, font=F["prod"], fill=C["ink"])
        y += H_TITULO
    tag = r.accion if r.tiene_costo else "ERROR"
    tw = d.textlength(tag, font=F["tag"]) + 36
    d.rounded_rectangle([x0 + ancho - 28 - tw, y0 + 22, x0 + ancho - 28, y0 + 66], 8, fill=C[tag][0])
    d.text((x0 + ancho - 28 - tw + 18, y0 + 30), tag, font=F["tag"], fill=C[tag][1])
    if not r.tiene_costo:
        d.text((x, y + 8), r.error or "Error", font=F["sub"], fill=C["SUBIR"][1])
        return
    y += 12

    def celdas(items, xx, yy, ancho_total, tam=26):
        cw = ancho_total / len(items)
        for k, (etq, val, *color) in enumerate(items):
            cx = xx + k * cw
            d.text((cx, yy), etq.upper(), font=F["lbl"], fill=C["mut"])
            _texto_ajustado(d, (cx, yy + 24), val, int(cw - 12), tam, color[0] if color else C["ink"])

    # 1. Proveedor
    d.text((x, y), f"COTIZACIÓN DEL PROVEEDOR · {mon}", font=F["sec"], fill=C["accent"])
    celdas([("Piezas", fmt.cant(r.linea.cantidad)), ("Peso pieza kg", fmt.num(r.linea.peso)),
            ("Pieza s/IVA", fmt.num(r.pieza_sin_iva)), ("Pieza c/IVA", fmt.num(r.pieza_con_iva)),
            ("Total c/IVA", fmt.num(r.total_con_iva))], x, y + 32, w)
    y += H_PROV

    # 2. Nuestro costo | Actual FERRE / MCY
    caja_w = (w - 16) / 2
    for i, (titulo, items) in enumerate((
        ("NUESTRO COSTO · $ INTERNO", [("Pieza", fmt.num(r.costo_pieza, 4)), ("Kilo", fmt.num(r.costo_kg, 4))]),
        ("ACTUAL FERRE / MCY · P3", [("Pieza", fmt.num(r.linea.p3_ferre)), ("Kilo", fmt.num(r.kilo_p3, 4))]),
    )):
        bx = x + i * (caja_w + 16)
        d.rounded_rectangle([bx, y, bx + caja_w, y + H_CAJAS - 16], 10, fill=C["caja"])
        d.text((bx + 18, y + 14), titulo, font=F["sec"], fill=C["accent"] if i == 0 else C["ink"])
        celdas(items, bx + 18, y + 48, caja_w - 36, tam=30)
    y += H_CAJAS

    # 3. Precio sugerido (tabla 17 % / 18 %)
    d.text((x, y), "PRECIO SUGERIDO", font=F["sec"], fill=C["accent"])
    y += 32
    cols = [("Margen", 0.0), ("Pieza $", 0.24), ("Kilo $", 0.48), ("P3 actual vs sugerido", 0.70)]
    d.rectangle([x, y, x + w, y + 34], fill=C["caja"])
    for etq, f in cols:
        d.text((x + 14 + f * w, y + 8), etq.upper(), font=F["lbl"], fill=C["mut"])
    y += 34
    filas = [(p.margen_min, r.costo_min, r.kg_min, r.dif_min), (p.margen_obj, r.costo_obj, r.kg_obj, r.dif_obj)]
    for j, (m, pieza, kilo, dif) in enumerate(filas):
        fy = y + j * 48
        if j == 1:
            d.rectangle([x, fy, x + w, fy + 48], fill=C["resalte"])
        d.line([x, fy + 48, x + w, fy + 48], fill=C["line"], width=1)
        d.text((x + 14, fy + 11), f"+{m:g}%", font=F["bold"], fill=C["ink"])
        d.text((x + 14 + 0.24 * w, fy + 10), fmt.num(pieza), font=F["val"], fill=C["ink"])
        d.text((x + 14 + 0.48 * w, fy + 10), fmt.num(kilo, 4), font=F["val"], fill=C["ink"])
        color = C["SUBIR"][1] if dif < 0 else C["MANTENER"][1]
        d.text((x + 14 + 0.70 * w, fy + 10), fmt.pct(dif), font=F["val"], fill=color)
    y += 96 + (H_TABLA - 32 - 34 - 96)

    # 4. Recomendación
    fondo, letra = C[r.accion]
    d.rounded_rectangle([x, y, x + w, y + H_FRANJA - 14], 10, fill=fondo)
    if r.accion == "SUBIR":
        txt = f"SUBIR el P3 a {fmt.num(r.p3_sugerido)}  ·  kilo {fmt.num(r.p3_sugerido / r.linea.peso, 4)}"
    elif r.accion == "REVISAR":
        txt = f"REVISAR: margen entre {p.margen_min:g}% y {p.margen_obj:g}%  ·  sugerido {fmt.num(r.p3_sugerido)}"
    elif r.accion == "ERROR":
        txt = f"Sin P3 en la lista de precios: no se puede decidir · sugerido {fmt.num(r.p3_sugerido)}"
    else:
        txt = f"MANTENER: el P3 actual cubre el {p.margen_obj:g}% ({fmt.pct(r.dif_obj)})"
    d.text((x + 18, y + 13), txt, font=F["bold"], fill=letra)
    y += H_FRANJA

    # 5. Última compra
    if ult:
        costo_kg = ult.get("COSTO_KG")
        hist = f"Últ. compra {fmt.fecha(ult['FECHA'])} · {ult['PROVEEDOR']} · {fmt.num(ult['PRECIO'])}" + (
            f" · kg {fmt.num(costo_kg, 4)}" if fmt.es_numero(costo_kg) else "")
        d.text((x, y + 4), _envolver(d, hist, F["small"], w)[0], font=F["small"], fill=C["mut"])


def _fuentes_imagen() -> dict:
    return {
        "eyebrow": _fuente("DejaVuSansCondensed-Bold.ttf", 22),
        "title": _fuente("DejaVuSansCondensed-Bold.ttf", 50),
        "sub": _fuente("DejaVuSans.ttf", 23),
        "small": _fuente("DejaVuSans.ttf", 20),
        "prod": _fuente("DejaVuSansCondensed-Bold.ttf", 30),
        "tag": _fuente("DejaVuSansCondensed-Bold.ttf", 24),
        "sec": _fuente("DejaVuSansCondensed-Bold.ttf", 19),
        "lbl": _fuente("DejaVuSansCondensed-Bold.ttf", 16),
        "bold": _fuente("DejaVuSans-Bold.ttf", 22),
        "val": _fuente("DejaVuSansMono.ttf", 25),
        "cnt": _fuente("DejaVuSansMono.ttf", 32),
        "hoja": _fuente("DejaVuSansCondensed-Bold.ttf", 24),
    }


def _textos_cabecera(res: Resultado, p: Parametros, cond: Condiciones, ancho: int, F: dict, medidor) -> list:
    mon = "Bs" if cond.moneda == "bs" else "$"
    desc = " + ".join(f"{fmt.num(x)}%" for x in cond.descuentos)
    return [
        (f"Pedido {fmt.fecha(p.fecha)}  ·  BCV $ {fmt.num(p.tasa_bcv)}"
         + (f"  ·  BCV € {fmt.num(p.tasa_bcv_eur)}" if describir_tasas(cond) else "")
         + f"  ·  Interna {fmt.num(p.tasa_interna)}", F["sub"], C["head2"]),
        *[(l, F["sub"], C["head2"]) for l in _envolver(medidor, f"Cotiza en {mon} · {describir_iva(cond, p.iva)} · {describir_pago(cond)}", F["sub"], ancho)],
        *[(l, F["small"], C["head3"]) for l in _envolver(medidor, (f"Desc. {desc} · " if desc else "") + f"Flete {fmt.num(res.flete_kg, 4)} $/kg · Márgenes {p.margen_min:g}% / {p.margen_obj:g}% · costos en $ interno", F["small"], ancho)],
    ]


def _textos_resumen(res: Resultado, cond: Condiciones, ancho: int, F: dict, medidor) -> list:
    """Líneas de la caja de totales y pago (se parten en vez de cortarse)."""
    mon = "Bs" if cond.moneda == "bs" else "$"
    t, pl = res.totales, res.plan
    lineas = []
    if not t.lineas:
        return lineas

    def agregar(texto, fuente, color):
        lineas.extend((l, fuente, color) for l in _envolver(medidor, texto, fuente, ancho))

    agregar(f"{fmt.num(t.kg / 1000)} t · Total s/IVA {mon} {fmt.num(t.sin_iva)} · IVA {mon} {fmt.num(t.iva)} · c/IVA {mon} {fmt.num(t.con_iva)}", F["sub"], C["ink"])
    if cond.moneda == "usd":
        agregar(f"Pago: $ {fmt.num(pl.usd)} en dólares · Bs {fmt.num(pl.bs_total)} a BCV (IVA Bs {fmt.num(pl.bs_iva)})", F["sub"], C["mut"])
    else:
        agregar(f"Pago: Bs {fmt.num(pl.bs_total)} (IVA Bs {fmt.num(pl.bs_iva)})", F["sub"], C["mut"])
    if pl.igtf:
        agregar(f"IGTF {cond.igtf_pct:g}%: $ {fmt.num(pl.igtf)} (incluido en el costo)", F["sub"], C["mut"])
    if pl.retencion_pct:
        ret_bcv, ret_int = pl.en_dolares(pl.bs_iva_retenido)
        agregar(f"Retención IVA {pl.retencion_pct:g}% al SENIAT: Bs {fmt.num(pl.bs_iva_retenido)} · "
                f"$ {fmt.num(ret_bcv)} BCV · $ {fmt.num(ret_int)} interno", F["sub"], C["mut"])
        al_bcv, al_int = pl.en_dolares(pl.bs_al_proveedor)
        partes = ([f"$ {fmt.num(pl.usd)} en dólares"] if pl.usd else []) + [
            f"Bs {fmt.num(pl.bs_al_proveedor)} ($ {fmt.num(al_bcv)} BCV · $ {fmt.num(al_int)} interno)"]
        agregar("Al proveedor: " + " + ".join(partes), F["sub"], C["mut"])
    agregar(f"Gasto total $ interno {fmt.num(pl.gasto_int)} · {fmt.num(pl.gasto_int / t.kg if t.kg else float('nan'), 4)} $/kg", F["bold"], C["ink"])
    return lineas


PRODUCTOS_POR_HOJA = 3


def imagenes(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones, historial=None, autor: str = "",
             por_hoja: int = PRODUCTOS_POR_HOJA) -> list[bytes]:
    """Hojas PNG (1080 px de ancho) para WhatsApp: hasta ``por_hoja`` productos por hoja.

    Cada hoja repite el mismo encabezado (proveedor, tasas, condiciones), el conteo
    SUBIR / REVISAR / MANTENER y la caja de totales y pago, y lleva «Hoja i de n».
    """
    W, P = 1080, 56
    IW = W - 2 * P
    F = _fuentes_imagen()
    mon = "Bs" if cond.moneda == "bs" else "$"
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lineas_cab = _textos_cabecera(res, p, cond, IW, F, medidor)
    head_h = 166 + len(lineas_cab) * 40
    lineas_res = _textos_resumen(res, cond, IW - 40, F, medidor)
    sum_h = 84 + 20 + 40 * len(lineas_res) + 36 if lineas_res else 110
    foot_h = 110

    bloques = []
    for r in res.lineas:
        nl = _envolver(medidor, r.linea.descripcion or "(sin descripción)", F["prod"], IW - 240)[:2]
        ult = historial.ultima(r.linea.descripcion) if historial is not None else None
        bloques.append((r, nl, ult, _alto_producto(r, len(nl), ult)))
    por_hoja = max(1, int(por_hoja))
    grupos = [bloques[i:i + por_hoja] for i in range(0, len(bloques), por_hoja)] or [[]]
    cnt = res.conteo()
    generado = fmt.ahora().strftime("%d/%m/%Y %H:%M")

    hojas = []
    for n_hoja, grupo in enumerate(grupos, start=1):
        H = head_h + sum_h + sum(b[3] + 20 for b in grupo) + foot_h
        img = Image.new("RGB", (W, H), C["bg"])
        d = ImageDraw.Draw(img)

        # Encabezado (igual en todas las hojas)
        d.rectangle([0, 0, W, head_h], fill=C["head"])
        d.text((P, 50), "COSTEO DE COMPRA · ACEVAL", font=F["eyebrow"], fill=C["acc"])
        if len(grupos) > 1:
            etq = f"HOJA {n_hoja} DE {len(grupos)}"
            d.text((W - P - d.textlength(etq, font=F["hoja"]), 48), etq, font=F["hoja"], fill="#FFFFFF")
        d.text((P, 84), _envolver(d, prov.nombre, F["title"], IW)[0], font=F["title"], fill="#FFFFFF")
        for i, (texto, fuente, color) in enumerate(lineas_cab):
            d.text((P, 166 + i * 40), texto, font=fuente, fill=color)

        # Conteo y totales del costeo completo
        y, ancho = head_h + 28, (IW - 32) / 3
        for i, k in enumerate(("SUBIR", "REVISAR", "MANTENER")):
            x = P + i * (ancho + 16)
            d.rounded_rectangle([x, y, x + ancho, y + 64], 10, fill=C[k][0])
            d.text((x + 20, y + 12), str(cnt.get(k, 0)), font=F["cnt"], fill=C[k][1])
            d.text((x + 80, y + 18), k, font=F["tag"], fill=C[k][1])
        if lineas_res:
            alto_caja = 20 + 40 * len(lineas_res)
            d.rounded_rectangle([P, y + 84, P + IW, y + 84 + alto_caja], 12, fill=C["panel"], outline=C["line"], width=2)
            for k, (texto, fuente, color) in enumerate(lineas_res):
                d.text((P + 20, y + 100 + 40 * k), texto, font=fuente, fill=color)

        y = head_h + sum_h
        for r, nl, ult, alto in grupo:
            _tarjeta_producto(d, P, y, IW, alto, r, nl, ult, p, mon, F)
            y += alto + 20

        if autor:
            d.text((P, H - 76), f"Elaborado por: {autor}", font=F["small"], fill=C["mut"])
        pie = f"Generado {generado}" + (f" · Hoja {n_hoja} de {len(grupos)}" if len(grupos) > 1 else "")
        d.text((P, H - 44), pie, font=F["small"], fill=C["mut"])

        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        hojas.append(out.getvalue())
    return hojas


def imagen(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones, historial=None, autor: str = "") -> bytes:
    """Una sola imagen con todos los productos (compatibilidad)."""
    return imagenes(res, p, prov, cond, historial, autor, por_hoja=max(1, len(res.lineas)))[0]


# ---------------------------------------------------------------------------
# PDF para imprimir: carta horizontal, una fila por producto
# ---------------------------------------------------------------------------
def pdf_imprimir(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones, autor: str = "") -> bytes:
    """PDF tamaño carta horizontal (200 ppp), con el mismo encabezado en cada hoja y una
    tabla con una fila por producto. La primera hoja lleva además los totales y el pago."""
    W, H, M = 2200, 1700, 70           # 11 × 8,5 pulgadas a 200 ppp
    IW = W - 2 * M
    F = {
        "eyebrow": _fuente("DejaVuSansCondensed-Bold.ttf", 24),
        "title": _fuente("DejaVuSansCondensed-Bold.ttf", 52),
        "sub": _fuente("DejaVuSans.ttf", 26),
        "small": _fuente("DejaVuSans.ttf", 22),
        "bold": _fuente("DejaVuSans-Bold.ttf", 26),
        "th": _fuente("DejaVuSansCondensed-Bold.ttf", 21),
        "td": _fuente("DejaVuSansMono.ttf", 24),
        "prod": _fuente("DejaVuSansCondensed-Bold.ttf", 24),
        "tag": _fuente("DejaVuSansCondensed-Bold.ttf", 23),
        "hoja": _fuente("DejaVuSansCondensed-Bold.ttf", 26),
        "cnt": _fuente("DejaVuSansCondensed-Bold.ttf", 26),
    }
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lineas_cab = _textos_cabecera(res, p, cond, IW, F, medidor)
    head_h = 150 + len(lineas_cab) * 40
    lineas_res = _textos_resumen(res, cond, IW - 40, F, medidor)
    res_h = 64 + ((20 + 42 * len(lineas_res) + 20) if lineas_res else 0)   # conteo + caja de totales (solo hoja 1)
    foot_h, th_h = 70, 62

    mmin, mobj = f"+{p.margen_min:g}%", f"+{p.margen_obj:g}%"
    cols = [  # (título, ancho relativo, alineación)
        ("PRODUCTO", 5.2, "l"), ("PIEZAS", 1.1, "r"), ("PESO KG", 1.1, "r"), ("PIEZA S/IVA", 1.35, "r"),
        ("COSTO PIEZA", 1.35, "r"), ("COSTO KG", 1.2, "r"), (f"PIEZA {mmin}", 1.35, "r"), (f"KG {mmin}", 1.2, "r"),
        (f"PIEZA {mobj}", 1.35, "r"), (f"KG {mobj}", 1.2, "r"), ("P3 ACTUAL", 1.35, "r"), ("KILO P3", 1.2, "r"),
        (f"VS {mobj}", 1.1, "r"), ("ACCIÓN", 1.45, "c"), ("P3 SUGERIDO", 1.45, "r"),
    ]
    tot_rel = sum(c[1] for c in cols)
    anchos = [IW * c[1] / tot_rel for c in cols]

    filas = []
    for r in res.lineas:
        ln = r.linea
        nombre = _envolver(medidor, ln.descripcion or "(sin descripción)", F["prod"], anchos[0] - 20)[:2]
        if not r.tiene_costo:
            celdas = [fmt.cant(ln.cantidad), fmt.num(ln.peso)] + ["—"] * 11 + [""]
            filas.append((nombre, celdas, "ERROR", None))
            continue
        celdas = [
            fmt.cant(ln.cantidad), fmt.num(ln.peso), fmt.num(r.pieza_sin_iva), fmt.num(r.costo_pieza, 4), fmt.num(r.costo_kg, 4),
            fmt.num(r.costo_min), fmt.num(r.kg_min, 4), fmt.num(r.costo_obj), fmt.num(r.kg_obj, 4),
            fmt.num(ln.p3_ferre) if ln.p3_ferre else "—", fmt.num(r.kilo_p3, 4), fmt.pct(r.dif_obj), "",
            "—" if r.accion in ("MANTENER", "ERROR") else fmt.num(r.p3_sugerido),
        ]
        filas.append((nombre, celdas, r.accion, r.dif_obj))

    def alto_fila(f):
        return 24 + 30 * len(f[0])

    # Reparto en hojas
    hojas_filas, actual = [], []
    disponible = H - head_h - 24 - res_h - th_h - foot_h
    for f in filas:
        if actual and sum(alto_fila(x) for x in actual) + alto_fila(f) > disponible:
            hojas_filas.append(actual)
            actual, disponible = [], H - head_h - 24 - th_h - foot_h
        actual.append(f)
    hojas_filas.append(actual)
    n = len(hojas_filas)
    cnt = res.conteo()
    generado = fmt.ahora().strftime("%d/%m/%Y %H:%M")

    paginas = []
    for k, grupo in enumerate(hojas_filas, start=1):
        img = Image.new("RGB", (W, H), "#FFFFFF")
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, head_h], fill=C["head"])
        d.text((M, 40), "COSTEO DE COMPRA · ACEVAL", font=F["eyebrow"], fill=C["acc"])
        etq = f"HOJA {k} DE {n}"
        d.text((W - M - d.textlength(etq, font=F["hoja"]), 38), etq, font=F["hoja"], fill="#FFFFFF")
        d.text((M, 72), _envolver(d, prov.nombre, F["title"], IW)[0], font=F["title"], fill="#FFFFFF")
        for i, (texto, fuente, color) in enumerate(lineas_cab):
            d.text((M, 150 + i * 40), texto, font=fuente, fill=color)
        y = head_h + 24

        if k == 1:
            x = M
            for etq_c in ("SUBIR", "REVISAR", "MANTENER"):
                txt = f"{cnt.get(etq_c, 0)}  {etq_c}"
                w = d.textlength(txt, font=F["cnt"]) + 40
                d.rounded_rectangle([x, y, x + w, y + 46], 8, fill=C[etq_c][0])
                d.text((x + 20, y + 8), txt, font=F["cnt"], fill=C[etq_c][1])
                x += w + 16
            y += 64
            if lineas_res:
                caja = 20 + 42 * len(lineas_res)
                d.rounded_rectangle([M, y, M + IW, y + caja], 10, fill=C["caja"], outline=C["line"], width=2)
                for i, (texto, fuente, color) in enumerate(lineas_res):
                    d.text((M + 20, y + 14 + 42 * i), texto, font=fuente, fill=color)
                y += caja + 20

        # Encabezado de la tabla
        d.rectangle([M, y, M + IW, y + th_h], fill=C["head"])
        x = M
        for (titulo, _, al), w in zip(cols, anchos):
            lineas_t = _envolver(d, titulo, F["th"], w - 16)[:2]
            for j, lt in enumerate(lineas_t):
                tw = d.textlength(lt, font=F["th"])
                tx = x + 10 if al == "l" else (x + w - 10 - tw if al == "r" else x + (w - tw) / 2)
                d.text((tx, y + (19 if len(lineas_t) == 1 else 6) + j * 26), lt, font=F["th"], fill="#FFFFFF")
            x += w
        y += th_h

        for idx, (nombre, celdas, accion, dif) in enumerate(grupo):
            h = alto_fila((nombre,))
            if idx % 2:
                d.rectangle([M, y, M + IW, y + h], fill=C["caja"])
            d.line([M, y + h, M + IW, y + h], fill=C["line"], width=1)
            for j, lt in enumerate(nombre):
                d.text((M + 10, y + 11 + j * 30), lt, font=F["prod"], fill=C["ink"])
            x = M + anchos[0]
            ty = y + (h - 28) / 2
            for c_i, (val, w) in enumerate(zip(celdas, anchos[1:]), start=1):
                titulo = cols[c_i][0]
                if titulo == "ACCIÓN":
                    tw = d.textlength(accion, font=F["tag"]) + 24
                    bx = x + (w - tw) / 2
                    d.rounded_rectangle([bx, ty - 4, bx + tw, ty + 32], 6, fill=C[accion][0])
                    d.text((bx + 12, ty), accion, font=F["tag"], fill=C[accion][1])
                else:
                    color = C["ink"]
                    if titulo.startswith("VS") and dif is not None:
                        color = C["SUBIR"][1] if dif < 0 else C["MANTENER"][1]
                    _texto_ajustado(d, (x + w - 10 - min(d.textlength(val, font=F["td"]), w - 20), ty), val, int(w - 20), 24, color)
                x += w
            y += h

        d.text((M, H - 50), (f"Elaborado por: {autor} · " if autor else "") + f"Generado {generado}", font=F["small"], fill=C["mut"])
        d.text((W - M - d.textlength(f"Hoja {k} de {n}", font=F["small"]), H - 50), f"Hoja {k} de {n}", font=F["small"], fill=C["mut"])
        paginas.append(img)

    out = io.BytesIO()
    paginas[0].save(out, format="PDF", save_all=True, append_images=paginas[1:], resolution=200)
    return out.getvalue()
