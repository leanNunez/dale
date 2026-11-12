"""Fictitious data for "Distribuidora El Hornero". Every name here is invented (design §5).

Money is integer cents (pesos x 100). Ids are uuid5 of the natural key, so reseeding is stable.
"""

from datetime import datetime, time
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

SLUG = "el-hornero"
NAME = "Distribuidora El Hornero"
COMPANY_ID = uuid5(NAMESPACE_URL, f"dale:{SLUG}")
TIMEZONE = "America/Argentina/Buenos_Aires"
_LOCAL = ZoneInfo(TIMEZONE)  # dates below are midnight in the company's own time, not UTC
PRICES_FROM = datetime(2026, 1, 1, tzinfo=_LOCAL)
# A price change that takes effect later (the D4 price-change eval case): sku -> (from, pesos).
FUTURE_PRICE = ("COLA-225", datetime(2026, 12, 1, tzinfo=_LOCAL), 2900)
OVERRIDABLE = {"zones": "name", "customers": "code", "products": "sku"}  # table -> natural key


def row_id(kind: str, key: str) -> UUID:
    return uuid5(COMPANY_ID, f"{kind}:{key}")


# name | ISO weekdays (1 = Monday) | cutoff (the day before delivery) | minimum in pesos
ZONES = """
Centro|1,4|18:00|30000
Norte|2,5|16:00|45000
Sur|3,6|12:00|60000
"""
# code | name | zone | active
CUSTOMERS = """
C-001|Almacen Don Tito|Centro|1
C-002|Kiosco La Esquinita|Centro|1
C-003|Autoservicio Los Teros|Norte|1
C-004|Despensa Dona Rosa|Norte|1
C-005|Mini Mercado El Gauchito|Sur|1
C-006|Fiambreria La Pampa Chica|Sur|1
C-007|Almacen Santa Rita|Centro|1
C-008|Kiosco Cerrado Definitivo|Norte|0
"""
# sku | name | brand | presentation | search terms | price in pesos | active
PRODUCTS = """
COLA-225|Gaseosa cola|Burbuja|2,25 L|cola gaseosa|2450|1
COLA-15|Gaseosa cola|Burbuja|1,5 L|cola gaseosa|1850|1
COLA-6X500|Gaseosa cola pack|Burbuja|6 x 500 ml|cola pack|6900|1
LIMA-225|Gaseosa lima limon|Burbuja|2,25 L|lima limon|2350|1
NARA-225|Gaseosa naranja|Burbuja|2,25 L|naranja|2350|1
POME-225|Gaseosa pomelo|Burbuja|2,25 L|pomelo|2350|1
AGUA-2|Agua sin gas|Manantial Sur|2 L|agua sin gas|1100|1
AGUA-6X2|Agua sin gas pack|Manantial Sur|6 x 2 L|agua pack|6200|1
AGUA-GAS-15|Agua con gas|Manantial Sur|1,5 L|agua con gas soda|1250|1
SODA-SIF|Soda en sifon|Manantial Sur|1,5 L|soda sifon|900|1
CERV-LAT|Cerveza rubia lata|Cerveceria del Tala|473 ml|birra cerveza lata|1400|1
CERV-12|Cerveza rubia lata pack|Cerveceria del Tala|12 x 473 ml|birra pack|15900|1
CERV-LIT|Cerveza rubia retornable|Cerveceria del Tala|1 L|birra litro|2300|1
CERV-NEG|Cerveza negra|Cerveceria del Tala|1 L|birra negra stout|2800|1
VINO-TIN|Vino tinto|Bodega Los Aromos|750 ml|vino tinto malbec|4200|1
VINO-BLA|Vino blanco|Bodega Los Aromos|750 ml|vino blanco|3900|1
VINO-CAJA|Vino tinto en caja|Bodega Los Aromos|1 L|vino caja tetra|2100|1
FERN-750|Aperitivo amargo|Amargo del Fogon|750 ml|fernet amargo aperitivo|9800|1
YERB-1|Yerba mate|Mateando|1 kg|yerba mate|5200|1
YERB-500|Yerba mate|Mateando|500 g|yerba mate|2800|1
AZUC-1|Azucar|Dulce Pampa|1 kg|azucar|1300|1
AZUC-10|Azucar|Dulce Pampa|10 x 1 kg|azucar fardo|12000|1
HARI-1|Harina 000|Molino Cuatro Vientos|1 kg|harina 000|900|1
FIDE-500|Fideos guiseros|La Nonna Vera|500 g|fideos guiseros tirabuzon|1150|1
FIDE-SPA|Fideos spaghetti|La Nonna Vera|500 g|fideos spaghetti tallarin|1150|1
ARRO-1|Arroz largo fino|Granos del Litoral|1 kg|arroz|1700|1
ACEI-900|Aceite de girasol|Girasol Dorado|900 ml|aceite girasol|3300|1
GALL-PAQ|Galletitas de agua|Crocantito|3 x 100 g|galletitas agua crackers|1500|1
GALL-DUL|Galletitas dulces|Crocantito|300 g|galletitas dulces|1900|1
PAPA-FRI|Papas fritas|Crocantito|150 g|papas fritas snack|2200|1
LECH-1|Leche entera larga vida|La Vaquita Azul|1 L|leche entera|1250|1
DULC-LEC|Dulce de leche|La Vaquita Azul|400 g|dulce de leche|2600|1
JABO-PAN|Jabon de tocador|Espuma Fina|3 x 90 g|jabon tocador|1800|1
DETE-3L|Detergente|Espuma Fina|750 ml|detergente lavavajillas|1700|1
LAVA-3L|Lavandina|Espuma Fina|2 L|lavandina|1000|1
GASE-VIE|Gaseosa cola descontinuada|Burbuja|3 L|cola vieja|2900|0
"""


def rows(table: str) -> list[list[str]]:
    return [line.split("|") for line in globals()[table.upper()].strip().splitlines()]


def build(overrides: dict[str, dict[str, dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Table name -> rows, with `overrides` ({table: {natural key: {column: value}}}) applied."""
    c = {"company_id": COMPANY_ID}
    zones = [
        {**c, "id": row_id("zone", name), "name": name, "cutoff_time": time.fromisoformat(cutoff)}
        | {"delivery_weekdays": [int(d) for d in days.split(",")]}
        | {"min_order_amount_cents": int(minimum) * 100}
        for name, days, cutoff, minimum in rows("zones")
    ]
    customers = [
        {**c, "id": row_id("customer", code), "code": code, "name": name}
        | {"zone_id": row_id("zone", zone), "active": active == "1"}
        for code, name, zone, active in rows("customers")
    ]
    products = [
        {**c, "id": row_id("product", sku), "sku": sku, "name": name, "brand": brand}
        | {"presentation": presentation, "search_terms": terms, "active": active == "1"}
        for sku, name, brand, presentation, terms, _, active in rows("products")
    ]
    prices = [
        {**c, "product_id": row_id("product", sku), "valid_from": PRICES_FROM}
        | {"unit_price_cents": int(pesos) * 100}
        for sku, *_, pesos, _ in rows("products")
    ]
    sku, valid_from, pesos = FUTURE_PRICE
    prices.append(
        {**c, "product_id": row_id("product", sku), "valid_from": valid_from}
        | {"unit_price_cents": pesos * 100}
    )
    company = [{"id": COMPANY_ID, "slug": SLUG, "name": NAME, "timezone": TIMEZONE}]
    tables = {"company": company, "zones": zones, "customers": customers, "products": products}
    tables["prices"] = prices
    for table, by_key in overrides.items():
        if table not in OVERRIDABLE:
            raise ValueError(f"cannot override table {table!r}; allowed: {', '.join(OVERRIDABLE)}")
        index = {r[OVERRIDABLE[table]]: r for r in tables[table]}
        for key, changes in by_key.items():
            if key not in index:
                raise ValueError(f"{table}: unknown key {key!r}")
            if not set(changes) <= set(index[key]) - {"id", "company_id", OVERRIDABLE[table]}:
                raise ValueError(f"{table}.{key}: cannot override {sorted(changes)}")
            index[key].update(changes)
    return tables
