"""Estructuras de datos del costeo.

Todas las clases son ``dataclasses`` simples para que el motor de cálculo sea
fácil de probar y de leer. Los nombres siguen el vocabulario de compras de ACEVAL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

# ---------------------------------------------------------------------------
# Valores permitidos (se validan al construir las condiciones)
# ---------------------------------------------------------------------------
MONEDAS = {"usd": "Dólares", "bs": "Bolívares"}
PRECIO_POR = {"pieza": "Pieza", "tonelada": "Tonelada", "kg": "Kilo"}
IVA_BASE = {"100": "El 100% de la base", "10": "Solo el 10% de la base"}
IVA_DESCUENTO = {
    False: "Sobre la base con descuento",
    True: "Sobre la base sin descuento (IVA full)",
}
FORMAS_PAGO = {
    "divisa": "100% en $ (o Bs a tasa interna)",
    "bcv": "100% en Bs a tasa BCV",
    "pct": "Un % en $, el resto en Bs a BCV",
    "monto": "Un monto en $, el resto en Bs a BCV",
}
MONEDAS_FLETE = {
    "usd": "$ (o Bs a tasa interna)",
    "bs": "Bolívares",
    "usd_bcv": "$ pagado en Bs a BCV",
}

ACCIONES = ("SUBIR", "REVISAR", "MANTENER", "ERROR")


class ErrorDeDatos(ValueError):
    """Error con un mensaje pensado para mostrarse tal cual a la usuaria."""


def _num(valor: Any, defecto: float = 0.0) -> float:
    """Convierte a float tolerando None, vacío y textos con coma decimal."""
    if valor is None:
        return defecto
    if isinstance(valor, (int, float)):
        return float(valor) if valor == valor else defecto  # NaN -> defecto
    texto = str(valor).strip().replace("$", "").replace(" ", "")
    if not texto:
        return defecto
    if "," in texto and "." in texto:
        # 1.234,56 (es-VE) o 1,234.56 (en-US): el último separador es el decimal
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    else:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return defecto


@dataclass
class Parametros:
    """Valores comunes a todos los proveedores para una cotización."""

    fecha: date
    tasa_bcv: float
    tasa_interna: float
    iva: float = 16.0             # %
    margen_min: float = 17.0      # % (piso)
    margen_obj: float = 18.0      # % (objetivo)
    iva_en_costo: bool = True     # el IVA forma parte del costo

    @property
    def factor_bcv(self) -> float:
        """BCV ÷ interna: lo que vale en $ interno un dólar pagado en Bs a tasa BCV."""
        if self.tasa_interna <= 0:
            return float("nan")
        return self.tasa_bcv / self.tasa_interna


@dataclass
class Condiciones:
    """Condiciones comerciales y de pago de un proveedor.

    Viven en el perfil del proveedor y se copian a cada cotización, donde se
    pueden cambiar sin tocar el perfil.
    """

    moneda: str = "usd"
    precio_por: str = "pieza"
    iva_incluido: bool = False
    iva_base: str = "100"
    iva_sin_descuento: bool = False  # el IVA se calcula sobre la base ANTES de descuentos (ACEROS LAMINADOS)
    pago: str = "divisa"
    pago_valor: float = 0.0          # % (pago = pct) o monto en $ (pago = monto)
    flete: float = 0.0               # monto del flete de una gandola
    flete_moneda: str = "usd"
    toneladas: float = 32.0          # toneladas por gandola
    flete_carga_real: bool = False   # repartir el flete sobre los kg reales del pedido
    descuentos: list[float] = field(default_factory=list)  # % en cascada, sobre la base
    igtf: bool = False               # se paga IGTF sobre la parte de la base pagada en dólares
    igtf_pct: float = 3.0
    retencion_iva: bool = False      # informativo: parte del IVA se retiene y se entera al SENIAT
    retencion_pct: float = 75.0

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        checks = [
            (self.moneda, MONEDAS, "moneda"),
            (self.precio_por, PRECIO_POR, "precio_por"),
            (self.iva_base, IVA_BASE, "iva_base"),
            (self.pago, FORMAS_PAGO, "pago"),
            (self.flete_moneda, MONEDAS_FLETE, "flete_moneda"),
        ]
        for valor, permitidos, nombre in checks:
            if valor not in permitidos:
                raise ErrorDeDatos(
                    f"Valor no válido para {nombre}: {valor!r}. "
                    f"Opciones: {', '.join(permitidos)}."
                )
        self.pago_valor = _num(self.pago_valor)
        self.flete = _num(self.flete)
        self.toneladas = _num(self.toneladas, 32.0) or 32.0
        self.descuentos = [d for d in (_num(x) for x in (self.descuentos or [])) if d]
        self.igtf = bool(self.igtf)
        self.igtf_pct = _num(self.igtf_pct, 3.0)
        self.retencion_iva = bool(self.retencion_iva)
        self.retencion_pct = _num(self.retencion_pct, 75.0)

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def desde_dict(cls, datos: dict[str, Any] | None) -> "Condiciones":
        datos = dict(datos or {})
        conocidos = {k: v for k, v in datos.items() if k in cls.__dataclass_fields__}
        return cls(**conocidos)

    def clave(self) -> tuple:
        """Huella para saber si dos condiciones son equivalentes."""
        usa_valor = self.pago in ("pct", "monto")
        return (
            self.moneda, self.precio_por, bool(self.iva_incluido), self.iva_base, bool(self.iva_sin_descuento),
            self.pago, round(self.pago_valor, 6) if usa_valor else 0.0,
            round(self.flete, 6), self.flete_moneda, round(self.toneladas, 6),
            bool(self.flete_carga_real), tuple(round(d, 6) for d in self.descuentos),
            bool(self.igtf), round(self.igtf_pct, 6) if self.igtf else 0.0,
            bool(self.retencion_iva), round(self.retencion_pct, 6) if self.retencion_iva else 0.0,
        )


@dataclass
class Proveedor:
    id: str
    nombre: str
    condiciones: Condiciones = field(default_factory=Condiciones)

    def a_dict(self) -> dict[str, Any]:
        return {"id": self.id, "nombre": self.nombre, "condiciones": self.condiciones.a_dict()}

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> "Proveedor":
        if not datos.get("id") or not datos.get("nombre"):
            raise ErrorDeDatos("Cada proveedor necesita 'id' y 'nombre'.")
        return cls(
            id=str(datos["id"]),
            nombre=str(datos["nombre"]),
            condiciones=Condiciones.desde_dict(datos.get("condiciones")),
        )


@dataclass
class Linea:
    """Un producto de la cotización."""

    descripcion: str
    cantidad: float          # piezas
    precio: float            # en la moneda y unidad de la cotización
    peso: float              # kg por pieza
    p3_ferre: float = 0.0    # $ por pieza
    p3_mcy: float = 0.0
    desc_extra: float = 0.0  # % adicional solo para esta línea


@dataclass
class ResultadoLinea:
    linea: Linea
    error: str | None = None
    # Proveedor (moneda de la cotización)
    precio_pieza: float = float("nan")      # precio por pieza tal como cotiza
    lista_sin_iva: float = float("nan")     # sin IVA, antes de descuentos
    factor_desc: float = 1.0
    pieza_sin_iva: float = float("nan")     # base neta (con descuentos)
    iva_pieza: float = float("nan")
    pieza_con_iva: float = float("nan")
    kg_sin_iva: float = float("nan")
    kg_con_iva: float = float("nan")
    kg_total: float = float("nan")
    total_sin_iva: float = float("nan")
    total_iva: float = float("nan")
    total_con_iva: float = float("nan")
    # Costo en $ interno
    base_int: float = float("nan")
    iva_int: float = float("nan")
    flete_pieza: float = float("nan")
    igtf_pieza: float = 0.0             # IGTF por pieza, en $
    costo_pieza: float = float("nan")
    costo_kg: float = float("nan")
    # Precio estimado y decisión
    costo_min: float = float("nan")
    costo_obj: float = float("nan")
    kg_min: float = float("nan")
    kg_obj: float = float("nan")
    kilo_p3: float = float("nan")
    dif_min: float = float("nan")           # P3 / (costo × 1,17) − 1
    dif_obj: float = float("nan")
    accion: str = "ERROR"
    p3_sugerido: float = float("nan")
    mcy_distinto: bool = False

    @property
    def tiene_costo(self) -> bool:
        """True si se pudo calcular el costo (aunque falte el P3 para decidir)."""
        return self.costo_pieza == self.costo_pieza and self.costo_pieza > 0


@dataclass
class PlanDePago:
    usd: float = 0.0             # base pagada en dólares
    usd_base_en_bs: float = 0.0  # dólares de base que se pagan en Bs a BCV
    usd_iva: float = 0.0         # IVA en $ (se paga en Bs a BCV)
    bs_base: float = 0.0
    bs_iva: float = 0.0
    flete_int: float = 0.0       # flete completo en $ interno
    igtf: float = 0.0            # IGTF pagado (en $)
    retencion_pct: float = 0.0   # % del IVA que se retiene (informativo, no cambia el costo)

    @property
    def bs_iva_retenido(self) -> float:
        """IVA que se retiene y se entera al SENIAT (no se le paga al proveedor)."""
        return self.bs_iva * self.retencion_pct / 100

    @property
    def bs_iva_proveedor(self) -> float:
        """IVA que sí se le paga al proveedor."""
        return self.bs_iva - self.bs_iva_retenido

    @property
    def bs_al_proveedor(self) -> float:
        return self.bs_base + self.bs_iva_proveedor
    gasto_int: float = 0.0       # todo lo pagado, en $ interno

    @property
    def bs_total(self) -> float:
        return self.bs_base + self.bs_iva


@dataclass
class Totales:
    lineas: int = 0
    piezas: float = 0.0
    kg: float = 0.0
    sin_iva: float = 0.0
    iva: float = 0.0
    base_int: float = 0.0
    iva_int: float = 0.0
    flete_asignado: float = 0.0
    igtf: float = 0.0
    costo: float = 0.0

    @property
    def con_iva(self) -> float:
        return self.sin_iva + self.iva


@dataclass
class Resultado:
    lineas: list[ResultadoLinea]
    totales: Totales
    plan: PlanDePago
    factor_base: float          # multiplica la base (moneda cotización) -> $ interno
    factor_iva: float           # multiplica el IVA (moneda cotización) -> $ interno
    porcion_divisa: float | None  # parte de la base pagada en $ (None si cotiza en Bs)
    flete_kg: float
    kg_reparto_flete: float
    tasa_iva_efectiva: float     # 0,16 o 0,016
    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def conteo(self) -> dict[str, int]:
        c = {a: 0 for a in ACCIONES}
        for r in self.lineas:
            c[r.accion] = c.get(r.accion, 0) + 1
        return c
