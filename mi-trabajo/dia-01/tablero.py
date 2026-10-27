import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "datos" / "dia-01"
OUTPUT = Path(__file__).with_name("tablero.html")


def read_csv(name, required_columns):
    path = DATA_DIR / name
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
        try:
            factor = int(row["piezas_por_unidad"])
        except ValueError as error:
            raise ValueError(f"{line}: factor de conversión no entero") from error
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
    totals = defaultdict(lambda: {"producidas": 0, "rechazadas": 0})
    seen_keys = set()
    months = set()
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

        key = (day.isoformat(), line, row["turno"], sku)
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

        totals[(day.isoformat(), line, row["turno"])]["producidas"] += (
            produced * lines[line]["factor"]
        )
        totals[(day.isoformat(), line, row["turno"])]["rechazadas"] += (
            rejected * lines[line]["factor"]
        )
        months.add(day.strftime("%Y-%m"))
    return totals, months, len(rows)


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
                    f"paros.csv: id_paro {event_id} tiene registros distintos; "
                    "revisar antes de sumar"
                )
            duplicate_rows += 1
            continue
        unique[event_id] = signature

        day = parse_date(row["fecha"], f"paros.csv fila {row_number}")
        if row["linea"] not in lines:
            raise ValueError(
                f"paros.csv fila {row_number}: línea desconocida {row['linea']}"
            )
        try:
            minutes = int(row["minutos"])
        except ValueError as error:
            raise ValueError(
                f"paros.csv fila {row_number}: minutos no enteros"
            ) from error
        if minutes < 0:
            raise ValueError(f"paros.csv fila {row_number}: minutos negativos")
        row["fecha"] = day.isoformat()
        row["minutos"] = minutes

    event_totals = defaultdict(lambda: {"minutos": 0, "paros": 0})
    stop_data = []
    months = set()
    for signature in unique.values():
        row = dict(signature)
        day = parse_date(row["fecha"], f"paros.csv {row['id_paro']}")
        line = row["linea"]
        shift = row["turno"]
        cause = row["causa"]
        minutes = int(row["minutos"])
        key = (day.isoformat(), line, shift)
        event_totals[key]["minutos"] += minutes
        event_totals[key]["paros"] += 1
        months.add(day.strftime("%Y-%m"))
        stop_data.append(
            {
                "id": row["id_paro"],
                "fecha": day.isoformat(),
                "mes": day.strftime("%Y-%m"),
                "linea": line,
                "turno": shift,
                "causa": cause,
                "minutos": minutes,
            }
        )
    return (
        event_totals,
        stop_data,
        months,
        len(rows),
        len(unique),
        duplicate_rows,
    )


def build_payload():
    lines, skus = load_catalogs()
    production, production_months, production_rows = load_production(lines, skus)
    (
        stop_totals,
        stops,
        stop_months,
        stop_rows,
        unique_stops,
        duplicate_rows,
    ) = load_stops(lines)

    summaries = []
    keys = sorted(set(production) | set(stop_totals))
    for key in keys:
        day, line, shift = key
        produced = production[key]["producidas"]
        rejected = production[key]["rechazadas"]
        stop = stop_totals[key]
        summaries.append(
            {
                "fecha": day,
                "mes": day[:7],
                "linea": line,
                "nombre_linea": lines[line]["nombre"],
                "turno": shift,
                "producidas": produced,
                "rechazadas": rejected,
                "buenas": produced - rejected,
                "minutos_paro": stop["minutos"],
                "paros": stop["paros"],
            }
        )

    return {
        "lineas": [
            {"id": line, **details}
            for line, details in sorted(lines.items())
        ],
        "meses": sorted(production_months | stop_months),
        "turnos": sorted({row["turno"] for row in summaries}),
        "resumenes": summaries,
        "paros": stops,
        "auditoria": {
            "filas_produccion": production_rows,
            "filas_paros": stop_rows,
            "eventos_paro_unicos": unique_stops,
            "filas_paro_duplicadas": duplicate_rows,
        },
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Tablero de producción y paros | Laboratorios Valtena</title>
  <style>
    :root {
      --ink: #182c39;
      --muted: #60727b;
      --line: #dce5e8;
      --paper: #f3f7f7;
      --card: #fff;
      --teal: #087f78;
      --teal-dark: #075d59;
      --blue: #477da4;
      --orange: #d97735;
      --red: #bd5148;
      --shadow: 0 8px 24px rgba(31, 55, 67, .06);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 15px/1.5 "Segoe UI", Arial, sans-serif;
    }
    header {
      padding: 28px max(24px, calc((100vw - 1440px) / 2));
      color: #fff;
      background: linear-gradient(115deg, #123b47, #087f78);
    }
    .eyebrow { margin: 0 0 4px; color: #bde7df; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(25px, 4vw, 36px); line-height: 1.2; }
    header p:last-child { margin: 8px 0 0; color: #e0f2ef; }
    main { max-width: 1440px; margin: auto; padding: 22px 24px 40px; }
    .filters, .card {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--card);
      box-shadow: var(--shadow);
    }
    .filters {
      display: grid;
      grid-template-columns: repeat(3, minmax(150px, 1fr)) auto;
      gap: 14px;
      align-items: end;
      padding: 16px;
      margin-bottom: 18px;
    }
    label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; font-weight: 700; }
    select, button {
      min-height: 40px;
      border: 1px solid #cbd8dc;
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    select { padding: 7px 10px; }
    button { padding: 7px 13px; color: var(--teal-dark); font-weight: 700; cursor: pointer; }
    button:hover { background: #eaf5f3; }
    :focus-visible { outline: 3px solid #ffbf69; outline-offset: 2px; }
    .kpis { display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr)); gap: 12px; margin-bottom: 18px; }
    .kpi { padding: 15px 16px; border-top: 3px solid var(--teal); }
    .kpi:nth-child(2) { border-top-color: var(--blue); }
    .kpi:nth-child(3) { border-top-color: var(--orange); }
    .kpi:nth-child(4) { border-top-color: var(--red); }
    .kpi:nth-child(5), .kpi:nth-child(6) { border-top-color: #718491; }
    .kpi-label { color: var(--muted); font-size: 12px; font-weight: 700; }
    .kpi-value { margin-top: 4px; font-size: clamp(20px, 2.3vw, 29px); font-weight: 750; letter-spacing: -.03em; white-space: nowrap; }
    .kpi-unit { color: var(--muted); font-size: 11px; }
    .grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(340px, 1fr); gap: 16px; align-items: stretch; margin-bottom: 16px; }
    .card { min-width: 0; padding: 18px; }
    .card h2 { margin: 0; font-size: 17px; }
    .sub { margin: 3px 0 14px; color: var(--muted); font-size: 12px; }
    .chart { width: 100%; height: 270px; overflow: visible; }
    .chart text { fill: var(--muted); font: 11px "Segoe UI", Arial, sans-serif; }
    .chart .axis { stroke: #dce5e8; stroke-width: 1; }
    .chart .series { fill: none; stroke: var(--teal); stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }
    .chart .dot { fill: #fff; stroke: var(--teal); stroke-width: 2.5; }
    .empty { min-height: 220px; display: grid; place-items: center; color: var(--muted); }
    .causes { display: grid; gap: 12px; max-height: 300px; overflow: auto; padding-right: 4px; }
    .cause { display: grid; gap: 5px; }
    .cause-head { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
    .cause-name { font-weight: 650; }
    .cause-stats { color: var(--muted); white-space: nowrap; }
    .bar-bg { height: 8px; overflow: hidden; border-radius: 9px; background: #eaf0f1; }
    .bar { height: 100%; min-width: 2px; border-radius: inherit; background: var(--teal); }
    .table-card { padding: 0; overflow: hidden; }
    .table-heading { display: flex; justify-content: space-between; gap: 12px; align-items: start; padding: 18px 18px 10px; }
    .table-wrap { max-height: 510px; overflow: auto; border-top: 1px solid var(--line); }
    .table-footer { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 10px 14px; color: var(--muted); font-size: 12px; }
    .page-controls { display: flex; gap: 8px; align-items: center; }
    .page-controls button { min-height: 32px; padding: 4px 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }
    thead { position: sticky; top: 0; z-index: 1; background: #edf4f4; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #e8edef; text-align: right; }
    th { color: #334b56; font-size: 11px; }
    td:first-child, th:first-child, td:nth-child(2), th:nth-child(2), td:nth-child(3), th:nth-child(3) { text-align: left; }
    th button { min-height: 0; padding: 0; border: 0; background: transparent; color: inherit; font-size: inherit; text-align: inherit; }
    th button:hover { color: var(--teal-dark); background: transparent; text-decoration: underline; }
    tbody tr:hover { background: #f5faf9; }
    .numeric { font-variant-numeric: tabular-nums; }
    .audit { margin: 14px 2px 0; color: var(--muted); font-size: 11px; }
    .footnote { margin: 10px 2px 0; color: var(--muted); font-size: 11px; }
    @media (max-width: 1000px) {
      .kpis { grid-template-columns: repeat(3, 1fr); }
      .grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 650px) {
      header { padding: 22px 18px; }
      main { padding: 16px 12px 28px; }
      .filters { grid-template-columns: 1fr 1fr; }
      .filters button { grid-column: 1 / -1; }
      .kpis { grid-template-columns: repeat(2, 1fr); gap: 8px; }
      .kpi { padding: 12px; }
      .card { padding: 14px; }
      .table-heading { padding: 14px; }
    }
  </style>
</head>
<body>
  <header>
    <p class="eyebrow">Laboratorios Valtena · análisis de planta</p>
    <h1>Producción y paros</h1>
    <p>Explora producción buena, rechazos y eventos de paro por periodo, línea y turno.</p>
  </header>
  <main>
    <section class="filters" aria-label="Filtros del tablero">
      <label>Línea
        <select id="line-filter"><option value="">Todas las líneas</option></select>
      </label>
      <label>Mes
        <select id="month-filter"><option value="">Todos los meses</option></select>
      </label>
      <label>Turno
        <select id="shift-filter"><option value="">Todos los turnos</option></select>
      </label>
      <button id="clear-filters" type="button">Limpiar filtros</button>
    </section>

    <section class="kpis" aria-label="Indicadores del filtro actual">
      <article class="card kpi"><div class="kpi-label">Piezas buenas</div><div class="kpi-value" id="kpi-good">0</div><div class="kpi-unit">piezas</div></article>
      <article class="card kpi"><div class="kpi-label">Producidas</div><div class="kpi-value" id="kpi-produced">0</div><div class="kpi-unit">piezas antes de rechazos</div></article>
      <article class="card kpi"><div class="kpi-label">Rechazadas</div><div class="kpi-value" id="kpi-rejected">0</div><div class="kpi-unit">piezas</div></article>
      <article class="card kpi"><div class="kpi-label">Tasa de rechazo</div><div class="kpi-value" id="kpi-rate">0%</div><div class="kpi-unit">rechazadas / producidas</div></article>
      <article class="card kpi"><div class="kpi-label">Minutos de paro</div><div class="kpi-value" id="kpi-minutes">0</div><div class="kpi-unit">minutos únicos</div></article>
      <article class="card kpi"><div class="kpi-label">Paros</div><div class="kpi-value" id="kpi-stops">0</div><div class="kpi-unit">eventos únicos</div></article>
    </section>

    <section class="grid">
      <article class="card">
        <h2>Piezas buenas por día</h2>
        <p class="sub">Suma diaria de piezas producidas menos piezas rechazadas.</p>
        <div id="daily-chart"></div>
      </article>
      <article class="card">
        <h2>Paros por causa</h2>
        <p class="sub">Minutos y cantidad de eventos únicos para los filtros seleccionados.</p>
        <div id="cause-chart"></div>
      </article>
    </section>

    <section class="card table-card">
      <div class="table-heading">
        <div>
          <h2>Detalle por día, línea y turno</h2>
          <p class="sub" style="margin-bottom:0">Haz clic en un encabezado para ordenar; vuelve a hacer clic para invertir el orden.</p>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr id="table-head"></tr></thead>
          <tbody id="table-body"></tbody>
        </table>
      </div>
      <div class="table-footer">
        <span id="row-count"></span>
        <div class="page-controls">
          <button id="previous-page" type="button">Anterior</button>
          <span id="page-count"></span>
          <button id="next-page" type="button">Siguiente</button>
        </div>
      </div>
    </section>
    <p class="audit" id="audit"></p>
    <p class="footnote">Producción y paros se agregan por separado y después se resumen por fecha/línea/turno para evitar multiplicar registros. Los minutos describen paros registrados; por sí solos no prueban la causa de cambios en producción.</p>
  </main>
  <script id="dashboard-data" type="application/json">__DASHBOARD_DATA__</script>
  <script>
    "use strict";
    const DATA = JSON.parse(document.getElementById("dashboard-data").textContent);
    const nf = new Intl.NumberFormat("es-MX");
    const pf = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 2 });
    const PAGE_SIZE = 100;
    const fields = [
      ["fecha", "Fecha", "text"],
      ["linea", "Línea", "text"],
      ["turno", "Turno", "text"],
      ["producidas", "Producidas (piezas)", "number"],
      ["rechazadas", "Rechazadas (piezas)", "number"],
      ["buenas", "Buenas (piezas)", "number"],
      ["tasa", "Rechazo (%)", "number"],
      ["minutos_paro", "Minutos de paro", "number"],
      ["paros", "Paros", "number"]
    ];
    let sortField = "fecha";
    let sortDirection = -1;
    let currentPage = 0;

    const lineFilter = document.getElementById("line-filter");
    const monthFilter = document.getElementById("month-filter");
    const shiftFilter = document.getElementById("shift-filter");
    for (const line of DATA.lineas) {
      const option = document.createElement("option");
      option.value = line.id;
      option.textContent = `${line.id} · ${line.nombre}`;
      lineFilter.append(option);
    }
    for (const month of DATA.meses) {
      const option = document.createElement("option");
      option.value = month;
      option.textContent = month;
      monthFilter.append(option);
    }
    for (const shift of DATA.turnos) {
      const option = document.createElement("option");
      option.value = shift;
      option.textContent = shift;
      shiftFilter.append(option);
    }

    function selectedRows() {
      return DATA.resumenes.filter(row =>
        (!lineFilter.value || row.linea === lineFilter.value) &&
        (!monthFilter.value || row.mes === monthFilter.value) &&
        (!shiftFilter.value || row.turno === shiftFilter.value)
      );
    }
    function selectedStops() {
      return DATA.paros.filter(row =>
        (!lineFilter.value || row.linea === lineFilter.value) &&
        (!monthFilter.value || row.mes === monthFilter.value) &&
        (!shiftFilter.value || row.turno === shiftFilter.value)
      );
    }
    function setText(id, value) {
      document.getElementById(id).textContent = value;
    }
    function renderKpis(rows, stops) {
      const totals = rows.reduce((sum, row) => {
        sum.producidas += row.producidas;
        sum.rechazadas += row.rechazadas;
        sum.buenas += row.buenas;
        return sum;
      }, { producidas: 0, rechazadas: 0, buenas: 0 });
      const minutes = stops.reduce((sum, stop) => sum + stop.minutos, 0);
      const rate = totals.producidas ? totals.rechazadas / totals.producidas * 100 : 0;
      setText("kpi-good", nf.format(totals.buenas));
      setText("kpi-produced", nf.format(totals.producidas));
      setText("kpi-rejected", nf.format(totals.rechazadas));
      setText("kpi-rate", `${pf.format(rate)}%`);
      setText("kpi-minutes", nf.format(minutes));
      setText("kpi-stops", nf.format(stops.length));
    }
    function renderDailyChart(rows) {
      const host = document.getElementById("daily-chart");
      const byDate = new Map();
      for (const row of rows) byDate.set(row.fecha, (byDate.get(row.fecha) || 0) + row.buenas);
      const points = [...byDate.entries()].sort((a, b) => a[0].localeCompare(b[0]));
      if (!points.length) {
        host.innerHTML = '<div class="empty">No hay producción para esta selección.</div>';
        return;
      }
      const width = 760, height = 270, left = 63, right = 16, top = 15, bottom = 39;
      const plotW = width - left - right, plotH = height - top - bottom;
      const maxValue = Math.max(...points.map(point => point[1]), 1);
      const step = Math.pow(10, Math.floor(Math.log10(maxValue)));
      const maxAxis = Math.ceil(maxValue / step) * step;
      const x = index => left + (points.length === 1 ? plotW / 2 : index / (points.length - 1) * plotW);
      const y = value => top + plotH - value / maxAxis * plotH;
      const yTicks = 4;
      let svg = `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Gráfica de piezas buenas por día">`;
      for (let i = 0; i <= yTicks; i++) {
        const value = maxAxis * i / yTicks, yy = y(value);
        svg += `<line class="axis" x1="${left}" y1="${yy}" x2="${width-right}" y2="${yy}"></line>`;
        svg += `<text x="${left-9}" y="${yy+4}" text-anchor="end">${nf.format(value)}</text>`;
      }
      const path = points.map((point, index) => `${index ? "L" : "M"} ${x(index)} ${y(point[1])}`).join(" ");
      svg += `<path class="series" d="${path}"></path>`;
      points.forEach((point, index) => {
        const label = `${point[0]}: ${nf.format(point[1])} piezas buenas`;
        svg += `<circle class="dot" cx="${x(index)}" cy="${y(point[1])}" r="3.5"><title>${label}</title></circle>`;
      });
      const labelIndexes = new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]);
      for (const index of labelIndexes) {
        const label = points[index][0].slice(5);
        svg += `<text x="${x(index)}" y="${height-12}" text-anchor="middle">${label}</text>`;
      }
      svg += "</svg>";
      host.innerHTML = svg;
    }
    function renderCauses(stops) {
      const host = document.getElementById("cause-chart");
      const causes = new Map();
      for (const stop of stops) {
        const total = causes.get(stop.causa) || { minutos: 0, paros: 0 };
        total.minutos += stop.minutos;
        total.paros += 1;
        causes.set(stop.causa, total);
      }
      const sorted = [...causes.entries()].sort((a, b) =>
        b[1].minutos - a[1].minutos || a[0].localeCompare(b[0], "es")
      );
      if (!sorted.length) {
        host.innerHTML = '<div class="empty">No hay paros para esta selección.</div>';
        return;
      }
      const maxMinutes = Math.max(...sorted.map(([, value]) => value.minutos), 1);
      host.innerHTML = `<div class="causes">${sorted.map(([cause, value]) => {
        const percent = value.minutos / maxMinutes * 100;
        const item = document.createElement("span");
        item.textContent = cause;
        const safeCause = item.innerHTML;
        return `<div class="cause"><div class="cause-head"><span class="cause-name">${safeCause}</span><span class="cause-stats">${nf.format(value.minutos)} min · ${nf.format(value.paros)} paros</span></div><div class="bar-bg" aria-label="${safeCause}: ${nf.format(value.minutos)} minutos"><div class="bar" style="width:${percent}%"></div></div></div>`;
      }).join("")}</div>`;
    }
    function renderTable(rows, stops) {
      const stopByKey = new Map();
      for (const stop of stops) {
        const key = `${stop.fecha}|${stop.linea}|${stop.turno}`;
        const totals = stopByKey.get(key) || { minutos: 0, paros: 0 };
        totals.minutos += stop.minutos;
        totals.paros += 1;
        stopByKey.set(key, totals);
      }
      const tableRows = rows.map(row => {
        const key = `${row.fecha}|${row.linea}|${row.turno}`;
        const stop = stopByKey.get(key) || { minutos: 0, paros: 0 };
        return { ...row, minutos_paro: stop.minutos, paros: stop.paros,
          tasa: row.producidas ? row.rechazadas / row.producidas * 100 : null };
      });
      tableRows.sort((a, b) => {
        const av = a[sortField], bv = b[sortField];
        const compare = typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av ?? "").localeCompare(String(bv ?? ""), "es", { numeric: true });
        return compare * sortDirection;
      });
      const head = document.getElementById("table-head");
      head.replaceChildren();
      for (const [field, label] of fields) {
        const th = document.createElement("th");
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = `${label}${sortField === field ? (sortDirection === 1 ? " ▲" : " ▼") : ""}`;
        button.setAttribute("aria-label", `Ordenar por ${label}`);
        button.addEventListener("click", () => {
          if (sortField === field) sortDirection *= -1;
          else { sortField = field; sortDirection = 1; }
          currentPage = 0;
          render();
        });
        th.append(button);
        head.append(th);
      }
      const body = document.getElementById("table-body");
      body.replaceChildren();
      const fragment = document.createDocumentFragment();
      const pageCount = Math.max(1, Math.ceil(tableRows.length / PAGE_SIZE));
      currentPage = Math.min(currentPage, pageCount - 1);
      const firstIndex = currentPage * PAGE_SIZE;
      for (const row of tableRows.slice(firstIndex, firstIndex + PAGE_SIZE)) {
        const tr = document.createElement("tr");
        const values = [
          row.fecha, `${row.linea} · ${row.nombre_linea}`, row.turno,
          nf.format(row.producidas), nf.format(row.rechazadas), nf.format(row.buenas),
          row.tasa === null ? "—" : `${pf.format(row.tasa)}%`,
          nf.format(row.minutos_paro), nf.format(row.paros)
        ];
        values.forEach((value, index) => {
          const td = document.createElement("td");
          td.textContent = value;
          if (index >= 3) td.className = "numeric";
          tr.append(td);
        });
        fragment.append(tr);
      }
      body.append(fragment);
      const firstShown = tableRows.length ? firstIndex + 1 : 0;
      const lastShown = Math.min(firstIndex + PAGE_SIZE, tableRows.length);
      setText("row-count", `Filas ${nf.format(firstShown)}–${nf.format(lastShown)} de ${nf.format(tableRows.length)}`);
      setText("page-count", `Página ${currentPage + 1} de ${pageCount}`);
      document.getElementById("previous-page").disabled = currentPage === 0;
      document.getElementById("next-page").disabled = currentPage >= pageCount - 1;
    }
    function render() {
      const rows = selectedRows();
      const stops = selectedStops();
      renderKpis(rows, stops);
      renderDailyChart(rows);
      renderCauses(stops);
      renderTable(rows, stops);
    }
    [lineFilter, monthFilter, shiftFilter].forEach(element =>
      element.addEventListener("change", () => { currentPage = 0; render(); })
    );
    document.getElementById("previous-page").addEventListener("click", () => {
      if (currentPage > 0) { currentPage -= 1; render(); }
    });
    document.getElementById("next-page").addEventListener("click", () => {
      currentPage += 1;
      render();
    });
    document.getElementById("clear-filters").addEventListener("click", () => {
      lineFilter.value = "";
      monthFilter.value = "";
      shiftFilter.value = "";
      currentPage = 0;
      render();
    });
    const audit = DATA.auditoria;
    setText("audit", `Fuente integrada al HTML: ${nf.format(audit.filas_produccion)} filas de producción; ${nf.format(audit.filas_paros)} filas de paros, ${nf.format(audit.eventos_paro_unicos)} eventos únicos y ${nf.format(audit.filas_paro_duplicadas)} filas idénticas excluidas. Sin conexión ni librerías externas.`);
    render();
  </script>
</body>
</html>
"""


def main():
    payload = build_payload()
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = (
        data_json.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    html = HTML_TEMPLATE.replace("__DASHBOARD_DATA__", data_json)
    OUTPUT.write_text(html, encoding="utf-8")
    audit = payload["auditoria"]
    print(f"Tablero creado: {OUTPUT}")
    print(
        f"Producción: {audit['filas_produccion']} filas. Paros: "
        f"{audit['filas_paros']} filas, {audit['eventos_paro_unicos']} eventos "
        f"únicos; {audit['filas_paro_duplicadas']} filas repetidas idénticas excluidas."
    )
    print(
        f"Periodos incluidos: {', '.join(payload['meses'])}. "
        f"Resumenes fecha/línea/turno: {len(payload['resumenes'])}."
    )


if __name__ == "__main__":
    main()
