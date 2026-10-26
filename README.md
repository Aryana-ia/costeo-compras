# Costeo de Compras ACEVAL

App en Streamlit para calcular **cuánto nos cuesta realmente** el material que compramos a cada proveedor y decidir si hay que **subir o mantener** el precio de venta P3 en FERRE / MCY.

Reemplaza el Excel de costeo: las fórmulas viven en un solo lugar (`costeo/calculo.py`), están probadas con `pytest` y cada condición del proveedor queda guardada en su perfil.

---

## Índice

1. [Qué hace](#qué-hace)
2. [Cómo calcula](#cómo-calcula)
3. [Proveedores y formas de pago](#proveedores-y-formas-de-pago)
4. [Archivos que se cargan](#archivos-que-se-cargan)
5. [Uso diario](#uso-diario)
6. [Instalación en tu PC](#instalación-en-tu-pc)
7. [Publicar en Streamlit Community Cloud](#publicar-en-streamlit-community-cloud)
8. [Dónde se guardan los datos](#dónde-se-guardan-los-datos)
9. [Estructura del proyecto](#estructura-del-proyecto)
10. [Pruebas](#pruebas)
11. [Preguntas abiertas](#preguntas-abiertas)

---

## Qué hace

- **Parámetros del día**: fecha del pedido, tasa BCV, tasa interna, IVA (16 %) y márgenes (17 % piso, 18 % objetivo).
- **Lista de precios ACEVAL**: se carga el listado maestro (`Listado_de_Precios_Nacional_Actualizado<FECHA>.xlsx`, hoja `CONSOLIDADO`) y la app toma el **peso** y el **P3 de FERRE y MCY** de cada producto.
- **Perfiles de proveedor**: moneda, si el precio trae IVA, IVA sobre el 100 % o el 10 %, forma de pago, flete y descuentos. Ya vienen **UNICOM** y **COMPLEJO**.
- **Buscador de productos**: escribes parte del nombre y trae peso y P3. También se pueden pegar filas copiadas de Excel.
- **Resultado** por producto:
  - Precio del proveedor por pieza y por kilo, sin IVA y con IVA.
  - Costo por pieza y por kilo en $ interno.
  - Costo +17 % y +18 %, comparados con el P3.
  - Recomendación (SUBIR / REVISAR / MANTENER) y P3 sugerido.
- **Cómo se paga**: cuánto va en dólares, cuántos Bs de base, cuántos Bs de IVA y el gasto total en $ interno.
- **Historial de compras**: última compra de cada producto y último precio de cada proveedor que lo vendió.
- **Exportes**: imagen PNG lista para WhatsApp y Excel con dos hojas (costeo y resumen de pago).

---

## Cómo calcula

Todo se lleva a **dólares a tasa interna** (“$ interno”), que es la unidad en la que comparamos con el P3.

| Paso | Qué hace | Fórmula |
|---|---|---|
| 1 | Precio por pieza | Por pieza: tal cual · por tonelada: `precio × peso ÷ 1000` · por kilo: `precio × peso` |
| 2 | Quitar el IVA si viene incluido | `base = precio ÷ (1 + IVA efectivo)` |
| 3 | Descuentos, **siempre sobre la base**, en cascada | `base × (1 − d1) × (1 − d2) …` |
| 4 | IVA | `base neta × 16 %` (o `× 16 % × 10 %` si el proveedor cobra IVA sobre el 10 %) |
| 4b | IVA «full» (ACEROS LAMINADOS) | Si el perfil dice *IVA sobre la base sin descuento*: `base ANTES de descuentos × 16 %`. La base que se paga sí lleva el descuento. |
| 5a | Base a $ interno | Parte pagada en $ (o Bs a tasa interna): `× 1` · parte pagada en Bs a BCV: `× BCV ÷ interna` |
| 5b | IVA a $ interno | Cotización en $: el IVA **siempre** se paga en Bs a BCV → `× BCV ÷ interna` |
| 5c | Cotización en Bs | Base e IVA `÷ interna` |
| 5d | IGTF (si se activa) | `3 % × parte de la base pagada en dólares` (base con descuentos). No aplica al IVA ni a lo pagado en Bs. Se suma al costo. |
| — | Retención de IVA (informativa) | Si se activa (75 % por defecto), «Cómo se paga» separa el IVA en lo retenido (al SENIAT) y lo que se paga al proveedor. **No cambia el costo**: el costo siempre lleva el 100 % del IVA. |
| 6 | Flete (tarifa por kilo) | `flete de una gandola ÷ 32.000 kg × peso de la pieza`. Ej.: 300 $ ÷ 32.000 = 0,009375 $/kg → 40 t pagan 375 $, 20 t pagan 187,50 $ |
| 7 | Costo | `costo pieza = base + IVA + flete + IGTF` · `costo kilo = costo pieza ÷ peso` |
| 8 | Precio estimado | `costo × 1,17` y `costo × 1,18` |
| 9 | Decisión | P3 < costo+17 % → **SUBIR** · entre 17 % y 18 % → **REVISAR** · P3 ≥ costo+18 % → **MANTENER** |
| 10 | P3 sugerido | `costo × 1,18`, redondeado **hacia arriba** a 4 decimales |

**Diferencia %** = `P3 ÷ (costo × 1,17) − 1`. Un valor negativo significa que el P3 está por debajo del estimado.

### Ejemplo verificado (UNICOM)

Cabilla 1/2" × 12 m · 11,93 kg · $ 11,20 sin IVA · BCV 210,50 · interna 285,00 · flete $ 1.100 por gandola:

| Concepto | Cálculo | Resultado |
|---|---|---:|
| Factor BCV ÷ interna | 210,50 ÷ 285,00 | 0,7386 |
| Base a $ interno (50 % $ + 50 % Bs BCV) | 11,20 × (0,5 + 0,5 × 0,7386) | 9,7361 |
| IVA a $ interno | 11,20 × 16 % × 0,7386 | 1,3236 |
| Flete | 1.100 ÷ 32.000 × 11,93 | 0,4101 |
| **Costo por pieza** | | **11,4698** |
| **Costo por kilo** | 11,4698 ÷ 11,93 | **0,9614** |
| Costo × 1,18 | | 13,5344 |
| Decisión con P3 12,40 | 12,40 < 11,4698 × 1,17 | **SUBIR** |

Este caso está en `tests/test_calculo.py`.

---

## Proveedores y formas de pago

| Forma de pago (cotización en $) | Base | IVA |
|---|---|---|
| 100 % en $ (o Bs a tasa interna) | × 1 | Bs a BCV |
| 100 % en Bs a tasa BCV | × BCV ÷ interna | Bs a BCV |
| Un % en $, el resto en Bs a BCV (**UNICOM: 50 %**) | % × 1 + resto × BCV ÷ interna | Bs a BCV |
| Un monto en $, el resto en Bs a BCV (**COMPLEJO**) | monto × 1 + (total − monto) × BCV ÷ interna | Bs a BCV |

**ACEROS LAMINADOS:** el descuento se aplica a la base, pero el IVA se cobra sobre la base completa (IVA full). En el perfil: *IVA con descuento o sin descuento* → **Sobre la base sin descuento**.

Ejemplo: base $ 100 con 10 % de descuento → se pagan $ 90 de base + $ 16 de IVA (no $ 14,40) = $ 106.

**COMPLEJO:** si la gandola cuesta 31.500 y se pagan 13.000 en dólares, escribes `13000`. La app reparte esa proporción entre todos los productos del pedido.

**Condiciones por cotización:** al elegir un proveedor se cargan las condiciones de su perfil. Si cambias algo, aplica **solo a esa cotización** y aparecen dos botones:

- **Guardar en el perfil**: la condición cambió de ahora en adelante.
- **Volver al perfil**: descarta los cambios.

---

## Archivos que se cargan

### Lista de precios

Se aceptan dos formatos.

**1. Listado maestro** (recomendado), hoja `CONSOLIDADO`:

| CODNIA | TIENDA | CODIGO | PRODUCTO | … | P3 $ | … | PESO KG | … |
|---|---|---|---|---|---|---|---|---|

La app detecta cuál tienda es FERRE y cuál MCY por el nombre. Si se equivoca, las eliges en una lista.

**2. Formato simple:**

| DESCRIPCION | PESO | P3 FERRE | P3 MCY |
|---|---|---|---|

- Los productos sin peso (arena, bloques, fletes, maquila…) se cargan igual, pero no se pueden costear por kilo.
- FERRE y MCY van al mismo nivel. Si falta uno, se completa con el otro.
- Si difieren, el resultado lo marca.

### Historial de compras

Descarga la **plantilla** desde la app (barra lateral → Historial de compras).

| Obligatorias | Opcionales |
|---|---|
| FECHA, PROVEEDOR, DESCRIPCION, PRECIO | COSTO KG, CANTIDAD, MONEDA, FACTURA / OC, RIF, CONTACTO, CONDICIONES DE PAGO, DESCUENTO %, OBSERVACION, TASA |

> **Importante:** la descripción se enlaza con la lista de precios ignorando mayúsculas, acentos y espacios dobles, pero las palabras deben ser iguales (`MTS` ≠ `M`). Al cargar, la app dice cuántos productos coinciden.

---

## Uso diario

1. En la barra lateral, revisa la **fecha del pedido** y la **tasa BCV**: al abrir la app se trae sola desde bcv.org.ve (respaldo: ve.dolarapi.com) y muestra su **fecha valor**. El botón 🔄 la vuelve a consultar; si no hay conexión, se escribe a mano. Luego coloca la **tasa interna**.
2. Si cambió, actualiza la **lista de precios** (barra lateral → Lista de precios ACEVAL → subir Excel → Guardar lista).
3. Elige el **proveedor**. Revisa forma de pago, flete y descuentos.
4. Agrega los productos con el buscador (cantidad y precio del proveedor) o pega las filas desde Excel.
5. Revisa el resultado: semáforo, **Cómo se paga** y el detalle paso a paso de cada producto.
6. Descarga la **imagen para WhatsApp** o el **Excel**.
7. Escribe la **factura / OC** (opcional) y toca **Guardar costeo en el historial**.
   - Cada producto queda registrado como una compra: fecha, proveedor, precio por pieza sin IVA, costo por kilo, cantidad, condiciones, tasa y factura.
   - Desde ese momento aparece como **«última compra»** en los costeos siguientes.
   - En la pestaña **📚 Costeos guardados** (también desde el celular) eliges cualquier costeo y descargas otra vez su **imagen para WhatsApp** y su **Excel**, o lo abres para editarlo con **✏️ Abrir para editar**.
   - Si guardaste desde otro equipo, toca **🔄 Recargar datos guardados** en la barra lateral.
   - **Descargar historial guardado** (barra lateral → Historial de compras) baja todas las compras registradas en Excel.
   - Si corriges algo y vuelves a guardar, el costeo se **actualiza**, no se duplica. Para registrar otra compra el mismo día con el mismo proveedor, usa **Guardar como costeo nuevo**.

---

## Instalación en tu PC

Requiere **Python 3.12** (también funciona con 3.11 y 3.13).

```bash
git clone https://github.com/Aryana-ia/costeo-compras.git
cd costeo-compras
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Se abre en `http://localhost:8501`. En tu PC, todo lo que guardes queda en la carpeta `data/`.

---

## Publicar en Streamlit Community Cloud

1. Entra a [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub.
2. **Create app** → repositorio `Aryana-ia/costeo-compras`, rama `main`, archivo `app.py`.
3. En **Advanced settings**, elige **Python 3.12**. Con 3.14 algunas dependencias aún no instalan.
4. (Recomendado) En **Secrets**, pega la configuración de GitHub (siguiente sección) para que los datos no se borren.
5. **Deploy**.

---

## Dónde se guardan los datos

| Dato | En tu PC | En Streamlit Cloud sin Secrets | En Streamlit Cloud con Secrets |
|---|---|---|---|
| Perfiles de proveedores | `data/proveedores.json` | se pierde al reiniciar | rama `datos` del repo |
| Lista de precios | `data/lista_precios.csv` | se pierde al reiniciar | rama `datos` del repo |
| Historial | `data/historial.csv` | se pierde al reiniciar | rama `datos` del repo |
| Costeos guardados | `data/costeos.csv` | se pierde al reiniciar | rama `datos` del repo |

Streamlit Cloud borra el disco cada vez que la app se reinicia. Para que los datos persistan:

1. En GitHub: **Settings → Developer settings → Fine-grained tokens → Generate new token**.
   - *Repository access*: solo `costeo-compras`.
   - *Permissions → Contents*: **Read and write**.
2. En Streamlit Cloud → tu app → **Settings → Secrets**, pega lo siguiente (ver `.streamlit/secrets.toml.example`):

   ```toml
   [github]
   token  = "github_pat_..."
   repo   = "Aryana-ia/costeo-compras"
   branch = "datos"
   ```

La app crea sola la rama `datos` y guarda ahí cada cambio. Usa una rama aparte de `main` porque **cada commit en `main` reinicia la app** en Streamlit Cloud.

> Los archivos de datos están en `.gitignore`: nunca se suben a `main` por accidente.

---

## Estructura del proyecto

```
costeo-compras/
├── app.py                    # Interfaz Streamlit (solo pantalla; sin fórmulas)
├── costeo/
│   ├── modelos.py            # Parametros, Condiciones, Proveedor, Linea, Resultado…
│   ├── calculo.py            # Motor de cálculo (puro, probado)
│   ├── catalogo.py           # Lectura de la lista de precios (maestro / simple)
│   ├── historial.py          # Lectura del historial y consulta de últimas compras
│   ├── almacen.py            # Guardado local + sincronización opcional con GitHub
│   ├── exportar.py           # Tabla, Excel e imagen PNG
│   ├── registro.py           # Guardar y reabrir costeos (historial y costeos.csv)
│   ├── tasas.py              # Tasa BCV automática (bcv.org.ve / ve.dolarapi.com)
│   └── formato.py            # Números 1.234,56, fechas dd/mm/aaaa, normalización
├── data/proveedores.json     # Perfiles iniciales (UNICOM, COMPLEJO)
├── assets/fonts/             # Fuentes DejaVu para la imagen (licencia incluida)
├── tests/                    # pytest
├── .streamlit/config.toml    # Tema
└── .github/workflows/        # Corre las pruebas en cada push
```

**Regla del proyecto:** toda fórmula nueva va en `costeo/calculo.py` con su prueba. `app.py` solo muestra y recoge datos.

### Agregar una forma de pago nueva

1. Agrega la opción en `FORMAS_PAGO` (`costeo/modelos.py`).
2. Calcula su `porcion_divisa` en el paso 5 de `calcular()` (`costeo/calculo.py`).
3. Agrega su texto en `describir_pago()`.
4. Escribe una prueba en `tests/test_calculo.py` con un caso hecho a mano.

---

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q
```

Cubren:

- Los casos de UNICOM (50/50) y COMPLEJO (monto fijo).
- IVA incluido, IVA sobre el 10 % y descuentos en cascada sobre la base.
- Cotización en Bs, precio por tonelada y flete en Bs con reparto real.
- El semáforo y los mensajes de error.
- La lectura de la lista maestra, del formato simple y del historial.
- El almacén local y que la app arranque sin errores.

GitHub Actions las corre en cada push a `main`.

---

## Preguntas abiertas

Supuestos actuales, a confirmar:

1. **COMPLEJO:** el monto de la gandola (ej. 31.500) es **sin IVA**. El monto en $ sale de la base, y el IVA se paga aparte en Bs a BCV.
2. **Flete:** por defecto en $ y **sin IVA**. Se cambia por proveedor.
3. **Flete:** se cobra como tarifa por kilo (flete ÷ 32 t × peso), pese lo que pese el pedido. Si alguna vez se paga la gandola completa aunque el pedido pese menos, se activa *Cobrar la gandola completa aunque el pedido pese menos*.

---

Elaborado por Ariana G. Romero Rodríguez · ACEVAL
