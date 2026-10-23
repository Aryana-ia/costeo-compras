"""Exportes del resultado: tabla, Excel e imagen PNG para WhatsApp."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from . import formato as fmt
from .calculo import describir_iva, describir_pago
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
            "Base $ int.": r.base_int,
            "IVA $ int.": r.iva_int,
            "Flete $ int.": r.flete_pieza,
            "Costo pieza $": r.costo_pieza,
            "Costo kg $": r.costo_kg,
            f"Costo +{p.margen_min:g}%": r.costo_min,
            f"Costo +{p.margen_obj:g}%": r.costo_obj,
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
        ("Tasa BCV", p.tasa_bcv),
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
        ("Total en Bs", pl.bs_total),
        ("Flete ($ interno)", pl.flete_int),
        ("Gasto total ($ interno)", pl.gasto_int),
        ("Gasto por kilo ($ interno)", pl.gasto_int / t.kg if t.kg else None),
    ]
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


def imagen(res: Resultado, p: Parametros, prov: Proveedor, cond: Condiciones, historial=None, autor: str = "") -> bytes:
    """Resumen vertical (1080 px de ancho) pensado para leerse en el teléfono."""
    W, P = 1080, 56
    IW = W - 2 * P
    F = {
        "eyebrow": _fuente("DejaVuSansCondensed-Bold.ttf", 22),
        "title": _fuente("DejaVuSansCondensed-Bold.ttf", 50),
        "sub": _fuente("DejaVuSans.ttf", 23),
        "small": _fuente("DejaVuSans.ttf", 20),
        "prod": _fuente("DejaVuSansCondensed-Bold.ttf", 30),
        "tag": _fuente("DejaVuSansCondensed-Bold.ttf", 24),
        "lbl": _fuente("DejaVuSansCondensed-Bold.ttf", 17),
        "bold": _fuente("DejaVuSans-Bold.ttf", 22),
        "cnt": _fuente("DejaVuSansMono.ttf", 32),
    }
    mon = "Bs" if cond.moneda == "bs" else "$"
    t, pl = res.totales, res.plan
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    bloques = []
    for r in res.lineas:
        nl = _envolver(medidor, r.linea.descripcion or "(sin descripción)", F["prod"], IW - 240)[:2]
        ult = historial.ultima(r.linea.descripcion) if historial is not None else None
        alto = 40 + len(nl) * 38 + (392 if r.tiene_costo else 40) + (44 if ult else 0) + 20
        bloques.append((r, nl, ult, alto))

    head_h, sum_h, foot_h = 300, (260 if t.lineas else 110), 110
    H = head_h + sum_h + sum(b[3] + 20 for b in bloques) + foot_h
    img = Image.new("RGB", (W, H), C["bg"])
    d = ImageDraw.Draw(img)

    # Cabecera
    d.rectangle([0, 0, W, head_h], fill=C["head"])
    d.text((P, 50), "COSTEO DE COMPRA · ACEVAL", font=F["eyebrow"], fill=C["acc"])
    d.text((P, 84), _envolver(d, prov.nombre, F["title"], IW)[0], font=F["title"], fill="#FFFFFF")
    d.text((P, 166), f"Pedido {fmt.fecha(p.fecha)}  ·  BCV {fmt.num(p.tasa_bcv)}  ·  Interna {fmt.num(p.tasa_interna)}", font=F["sub"], fill=C["head2"])
    d.text((P, 206), _envolver(d, f"Cotiza en {mon} · {describir_iva(cond, p.iva)} · {describir_pago(cond)}", F["sub"], IW)[0], font=F["sub"], fill=C["head2"])
    desc = " + ".join(f"{fmt.num(x)}%" for x in cond.descuentos)
    linea3 = (f"Desc. {desc} · " if desc else "") + f"Flete {fmt.num(res.flete_kg, 4)} $/kg · Márgenes {p.margen_min:g}% / {p.margen_obj:g}% · costos en $ interno"
    d.text((P, 250), _envolver(d, linea3, F["small"], IW)[0], font=F["small"], fill=C["head3"])

    # Conteo y totales
    cnt = res.conteo()
    y, ancho = head_h + 28, (IW - 32) / 3
    for i, k in enumerate(("SUBIR", "REVISAR", "MANTENER")):
        x = P + i * (ancho + 16)
        d.rounded_rectangle([x, y, x + ancho, y + 64], 10, fill=C[k][0])
        d.text((x + 20, y + 12), str(cnt.get(k, 0)), font=F["cnt"], fill=C[k][1])
        d.text((x + 80, y + 18), k, font=F["tag"], fill=C[k][1])
    if t.lineas:
        d.rounded_rectangle([P, y + 84, P + IW, y + 224], 12, fill=C["panel"], outline=C["line"], width=2)
        l1 = f"{fmt.num(t.kg / 1000)} t · Total s/IVA {mon} {fmt.num(t.sin_iva)} · IVA {mon} {fmt.num(t.iva)} · c/IVA {mon} {fmt.num(t.con_iva)}"
        l2 = (f"Pago: $ {fmt.num(pl.usd)} en dólares · Bs {fmt.num(pl.bs_total)} a BCV (IVA Bs {fmt.num(pl.bs_iva)})"
              if cond.moneda == "usd" else f"Pago: Bs {fmt.num(pl.bs_total)} (IVA Bs {fmt.num(pl.bs_iva)})")
        l3 = f"Gasto total $ interno {fmt.num(pl.gasto_int)} · {fmt.num(pl.gasto_int / t.kg if t.kg else float('nan'), 4)} $/kg"
        d.text((P + 20, y + 100), _envolver(d, l1, F["sub"], IW - 40)[0], font=F["sub"], fill=C["ink"])
        d.text((P + 20, y + 140), _envolver(d, l2, F["sub"], IW - 40)[0], font=F["sub"], fill=C["mut"])
        d.text((P + 20, y + 180), l3, font=F["bold"], fill=C["ink"])

    # Productos
    y = head_h + sum_h
    cw = (IW - 56) / 4
    for r, nl, ult, alto in bloques:
        d.rounded_rectangle([P, y, P + IW, y + alto], 14, fill=C["panel"], outline=C["line"], width=2)
        yy = y + 26
        for texto in nl:
            d.text((P + 28, yy), texto, font=F["prod"], fill=C["ink"])
            yy += 38
        tag = r.accion if r.tiene_costo else "ERROR"
        tw = d.textlength(tag, font=F["tag"]) + 36
        d.rounded_rectangle([P + IW - 28 - tw, y + 22, P + IW - 28, y + 66], 8, fill=C[tag][0])
        d.text((P + IW - 28 - tw + 18, y + 30), tag, font=F["tag"], fill=C[tag][1])
        if not r.tiene_costo:
            d.text((P + 28, yy + 4), r.error or "Error", font=F["sub"], fill=C["SUBIR"][1])
            y += alto + 20
            continue
        yy += 10
        filas = [
            [("Piezas", fmt.cant(r.linea.cantidad)), ("Peso kg", fmt.num(r.linea.peso)),
             (f"Pieza s/IVA {mon}", fmt.num(r.pieza_sin_iva)), (f"Pieza c/IVA {mon}", fmt.num(r.pieza_con_iva))],
            [("Costo pieza $", fmt.num(r.costo_pieza, 4)), ("Costo kg $", fmt.num(r.costo_kg, 4)),
             (f"Kg s/IVA {mon}", fmt.num(r.kg_sin_iva, 4)), ("Kilo P3", fmt.num(r.kilo_p3, 4))],
            [(f"Kg +{p.margen_min:g}%", fmt.num(r.kg_min, 4)), (f"Kg +{p.margen_obj:g}%", fmt.num(r.kg_obj, 4)),
             (f"vs {p.margen_min:g}%", fmt.pct(r.dif_min), r.dif_min < 0), (f"vs {p.margen_obj:g}%", fmt.pct(r.dif_obj), r.dif_obj < 0)],
            [(f"Pieza +{p.margen_obj:g}%", fmt.num(r.costo_obj)), ("P3 actual", fmt.num(r.linea.p3_ferre)),
             ("P3 sugerido", "—" if r.accion == "MANTENER" else fmt.num(r.p3_sugerido)), (f"Total c/IVA {mon}", fmt.num(r.total_con_iva))],
        ]
        d.rectangle([P + 28, yy + 2 * 96 - 12, P + IW - 28, yy + 2 * 96 - 10], fill=C["line"])
        for fi, fila in enumerate(filas):
            ry = yy + fi * 96
            for k, celda in enumerate(fila):
                cx = P + 28 + k * cw
                d.text((cx, ry), celda[0].upper(), font=F["lbl"], fill=C["mut"])
                color = (C["SUBIR"][1] if celda[2] else C["MANTENER"][1]) if len(celda) > 2 else C["ink"]
                tam = 28
                f = _fuente("DejaVuSansMono.ttf", tam)
                while d.textlength(celda[1], font=f) > cw - 14 and tam > 14:
                    tam -= 2
                    f = _fuente("DejaVuSansMono.ttf", tam)
                d.text((cx, ry + 28), celda[1], font=f, fill=color)
        yy += 4 * 96
        if ult:
            d.rectangle([P + 28, yy - 6, P + IW - 28, yy - 4], fill=C["line"])
            costo_kg = ult.get("COSTO_KG")
            txt = f"Últ. compra {fmt.fecha(ult['FECHA'])} · {ult['PROVEEDOR']} · {fmt.num(ult['PRECIO'])}" + (
                f" · kg {fmt.num(costo_kg, 4)}" if fmt.es_numero(costo_kg) else "")
            d.text((P + 28, yy + 6), _envolver(d, txt, F["small"], IW - 56)[0], font=F["small"], fill=C["mut"])
        y += alto + 20

    if autor:
        d.text((P, H - 76), f"Elaborado por: {autor}", font=F["small"], fill=C["mut"])
    d.text((P, H - 44), f"Generado {datetime.now().strftime('%d/%m/%Y %H:%M')}", font=F["small"], fill=C["mut"])

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
