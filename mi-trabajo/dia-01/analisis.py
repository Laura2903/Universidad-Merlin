import csv
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datos" / "dia-01"
MONTHS = (7, 8)


def read_csv(name, required_columns):
    path = DATA / name
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(required_columns) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{name}: faltan columnas {sorted(missing)}")
        return list(reader)


def parse_date(value, source):
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{source}: fecha inválida {value!r}") from error


def load_catalogs():
    line_rows = read_csv(
        "catalogo_lineas.csv",
        ("linea", "nombre", "unidad_reporte", "piezas_por_unidad"),
    )
    sku_rows = read_csv("catalogo_skus.csv", ("sku", "linea"))

    lines = {}
    for row in line_rows:
        line = row["linea"]
        if line in lines:
            raise ValueError(f"catalogo_lineas.csv: línea repetida {line}")
        factor = int(row["piezas_por_unidad"])
        if factor <= 0:
            raise ValueError(f"{line}: piezas_por_unidad debe ser mayor que cero")
        lines[line] = {
            "nombre": row["nombre"],
            "unidad": row["unidad_reporte"],
            "factor": factor,
        }

    skus = {}
    for row in sku_rows:
        sku = row["sku"]
        if sku in skus:
            raise ValueError(f"catalogo_skus.csv: SKU repetido {sku}")
        if row["linea"] not in lines:
            raise ValueError(f"{sku}: línea no encontrada {row['linea']}")
        skus[sku] = row["linea"]
    return lines, skus


def load_production(lines, skus):
    rows = read_csv(
        "produccion.csv",
        (
            "fecha",
            "linea",
            "turno",
            "sku",
            "unidades_producidas",
            "unidades_rechazadas",
        ),
    )
    totals = defaultdict(
        lambda: {
            "producidas": 0,
            "rechazadas": 0,
            "buenas": 0,
            "piezas_buenas": 0,
            "dias": set(),
            "filas": 0,
        }
    )
    seen_keys = set()

    for row_number, row in enumerate(rows, start=2):
        day = parse_date(row["fecha"], f"produccion.csv fila {row_number}")
        line = row["linea"]
        sku = row["sku"]
        if line not in lines:
            raise ValueError(f"produccion.csv fila {row_number}: línea desconocida {line}")
        if sku not in skus:
            raise ValueError(f"produccion.csv fila {row_number}: SKU desconocido {sku}")
        if skus[sku] != line:
            raise ValueError(
                f"produccion.csv fila {row_number}: {sku} pertenece a {skus[sku]}, no a {line}"
            )

        key = (day, line, row["turno"], sku)
        if key in seen_keys:
            raise ValueError(
                f"produccion.csv: registro repetido para fecha/línea/turno/SKU {key}"
            )
        seen_keys.add(key)

        try:
            produced = int(row["unidades_producidas"])
            rejected = int(row["unidades_rechazadas"])
        except ValueError as error:
            raise ValueError(
                f"produccion.csv fila {row_number}: cantidades no enteras"
            ) from error
        if produced < 0 or rejected < 0 or rejected > produced:
            raise ValueError(
                f"produccion.csv fila {row_number}: cantidades fuera de rango"
            )

        month = day.month
        if day.year == 2026 and month in MONTHS:
            item = totals[(line, month)]
            good = produced - rejected
            item["producidas"] += produced
            item["rechazadas"] += rejected
            item["buenas"] += good
            item["piezas_buenas"] += good * lines[line]["factor"]
            item["dias"].add(day)
            item["filas"] += 1
    return rows, totals


def load_stops(lines):
    rows = read_csv(
        "paros.csv",
        ("id_paro", "fecha", "linea", "turno", "minutos", "causa"),
    )
    unique = {}
    duplicate_rows = 0
    for row_number, row in enumerate(rows, start=2):
        event_id = row["id_paro"]
        if not event_id:
            raise ValueError(f"paros.csv fila {row_number}: id_paro vacío")
        signature = tuple(row.items())
        if event_id in unique:
            if unique[event_id] != signature:
                raise ValueError(
                    f"paros.csv: id_paro {event_id} tiene registros distintos; revisar antes de sumar"
                )
            duplicate_rows += 1
            continue
        unique[event_id] = signature

        day = parse_date(row["fecha"], f"paros.csv fila {row_number}")
        line = row["linea"]
        if line not in lines:
            raise ValueError(f"paros.csv fila {row_number}: línea desconocida {line}")
        try:
            minutes = int(row["minutos"])
        except ValueError as error:
            raise ValueError(
                f"paros.csv fila {row_number}: minutos no enteros"
            ) from error
        if minutes < 0:
            raise ValueError(f"paros.csv fila {row_number}: minutos negativos")

    cause_totals = defaultdict(lambda: defaultdict(int))
    line_totals = defaultdict(int)
    for signature in unique.values():
        row = dict(signature)
        day = parse_date(row["fecha"], f"paros.csv {row['id_paro']}")
        if day.year == 2026 and day.month in MONTHS:
            minutes = int(row["minutos"])
            cause_totals[(row["linea"], row["causa"])][day.month] += minutes
            line_totals[(row["linea"], day.month)] += minutes
    return len(rows), len(unique), duplicate_rows, cause_totals, line_totals


def main():
    lines, skus = load_catalogs()
    production_rows, production = load_production(lines, skus)
    (
        stop_rows,
        unique_stops,
        duplicate_stop_rows,
        cause_totals,
        line_stop_totals,
    ) = load_stops(lines)

    print("Comparación de producción buena: julio vs. agosto de 2026")
    print("Buena = producidas - rechazadas; conversión a piezas según catálogo.")
    print("Criterio principal: mayor caída porcentual del total mensual.")
    conversions = "; ".join(
        f"{line}: {details['factor']} pieza(s) por {details['unidad']}"
        for line, details in lines.items()
    )
    print(f"Conversión aplicada: {conversions}")
    print(
        f"\nProducción: {len(production_rows)} filas leídas. "
        f"Paros: {stop_rows} filas; {unique_stops} eventos únicos; "
        f"{duplicate_stop_rows} filas repetidas idénticas no sumadas."
    )
    print(
        "\nLínea | Julio producidas/rechazadas/buenas (unidad reporte) => piezas buenas | "
        "Agosto producidas/rechazadas/buenas (unidad reporte) => piezas buenas | "
        "Cambio piezas | Caída total % | Días Jul/Ago | Promedio piezas/día Jul/Ago | "
        "Caída promedio/día %"
    )

    changes = []
    for line, details in lines.items():
        july = production[(line, 7)]
        august = production[(line, 8)]
        if not july["piezas_buenas"]:
            raise ValueError(f"{line}: julio no tiene producción buena; no hay base porcentual")
        change = august["piezas_buenas"] - july["piezas_buenas"]
        decline_percent = -change / july["piezas_buenas"] * 100
        july_days = len(july["dias"])
        august_days = len(august["dias"])
        july_average = july["piezas_buenas"] / july_days if july_days else 0
        august_average = august["piezas_buenas"] / august_days if august_days else 0
        daily_decline_percent = (
            (1 - august_average / july_average) * 100 if july_average else 0
        )
        changes.append((line, decline_percent, change))
        print(
            f"{line} ({details['nombre']}) | "
            f"{july['producidas']:,}/{july['rechazadas']:,}/{july['buenas']:,} "
            f"=> {july['piezas_buenas']:,} | "
            f"{august['producidas']:,}/{august['rechazadas']:,}/{august['buenas']:,} "
            f"=> {august['piezas_buenas']:,} | {change:+,} | "
            f"{decline_percent:+.2f}% | {july_days}/{august_days} | "
            f"{july_average:,.1f}/{august_average:,.1f} | "
            f"{daily_decline_percent:+.2f}%"
        )

    top_line, top_decline, top_change = max(changes, key=lambda value: value[1])
    print(
        f"\nMayor caída porcentual: {top_line} ({lines[top_line]['nombre']}), "
        f"{top_decline:.2f}% ({top_change:,} piezas buenas)."
    )
    print(
        f"\nParos de {top_line} por causa (minutos; cambio = agosto - julio):"
    )
    line_causes = [
        (cause, months[7], months[8], months[8] - months[7])
        for (line, cause), months in cause_totals.items()
        if line == top_line
    ]
    for cause, july_minutes, august_minutes, change in sorted(
        line_causes, key=lambda item: item[2], reverse=True
    ):
        print(
            f"- {cause}: julio {july_minutes}, agosto {august_minutes}, "
            f"cambio {change:+} min"
        )
    july_stops = line_stop_totals[(top_line, 7)]
    august_stops = line_stop_totals[(top_line, 8)]
    print(
        f"Total de minutos de paro de {top_line}: julio {july_stops}, "
        f"agosto {august_stops}, cambio {august_stops - july_stops:+} min."
    )
    print(
        "\nNota: los paros muestran causas registradas y su duración; "
        "la coincidencia temporal no demuestra por sí sola causalidad."
    )


if __name__ == "__main__":
    main()
