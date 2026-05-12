#!/usr/bin/env python3
"""Generate an HTML explorer with SQL schema from table definition CSV files."""

from __future__ import annotations

import argparse
import csv
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final


CSV_GLOB: Final[str] = "*.csv"
# These suffixes belong to helper/metadata/value-list CSVs, not table schema definitions.
SKIPPED_TABLE_SUFFIXES: Final[tuple[str, ...]] = ("_optional.csv", "_fields.csv", "_codes.csv")
COLUMN_HEADER_ROW: Final[str] = (
    "<thead><tr><th>Column</th><th>Type</th><th>PK</th><th>Reference</th><th>Description</th></tr></thead>"
)


@dataclass
class Column:
    name: str
    sql_type: str
    external_table: str
    description: str
    is_primary_key: bool
    foreign_table: str | None
    foreign_column: str | None


@dataclass
class ValueTable:
    name: str
    headers: list[str]
    rows: list[list[str]]


def normalize_sql_type(raw_type: str) -> str:
    """Normalize a type token from CSV into a SQL-ish display value."""
    value = raw_type.strip()
    value = re.sub(r"\s*\(pk\)\s*", "", value, flags=re.IGNORECASE).strip()
    return value.upper() if value else "TEXT"


def split_foreign_reference(value: str) -> tuple[str | None, str | None]:
    """Parse `table:column` references while allowing a bare table name."""
    text = value.strip()
    if not text:
        return None, None
    if ":" not in text:
        return text, None
    table_name, col_name = text.split(":", 1)
    return table_name.strip(), col_name.strip() or None


def read_table_definition(csv_file: Path) -> list[Column]:
    """Load one schema-definition CSV into typed column entries."""
    with csv_file.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns: list[Column] = []
        for row in reader:
            raw_type = (row.get("type") or row.get("kind") or "").strip()
            raw_name = (row.get("element_name") or "").strip()
            raw_external = (row.get("external_table") or "").strip()
            raw_description = (row.get("description") or "").strip()
            if not raw_name:
                continue
            is_pk = "(pk)" in raw_type.lower()
            fk_table, fk_column = split_foreign_reference(raw_external)
            columns.append(
                Column(
                    name=raw_name,
                    sql_type=normalize_sql_type(raw_type),
                    external_table=raw_external,
                    description=raw_description,
                    is_primary_key=is_pk,
                    foreign_table=fk_table,
                    foreign_column=fk_column,
                )
            )
    return columns


def read_value_table(csv_file: Path) -> ValueTable | None:
    """Load a raw value table CSV used for valid-value lookup sections."""
    with csv_file.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return None
    headers = [h.strip() for h in rows[0]]
    if not any(headers):
        return None
    data_rows = [[cell.strip() for cell in row] for row in rows[1:]]
    return ValueTable(name=csv_file.stem, headers=headers, rows=data_rows)


def build_fk_html(column: Column, table_names: set[str]) -> str:
    """Render foreign-reference cell content with a local table link when possible."""
    if not column.foreign_table:
        return ""
    if column.foreign_table in table_names:
        return f'<a href="#table-{html.escape(column.foreign_table)}">{html.escape(column.external_table)}</a>'
    return html.escape(column.external_table)


def table_card_html(
    table_name: str, columns: list[Column], table_names: set[str], value_names: set[str]
) -> str:
    """Render one schema table card with columns and optional links to references/value tables."""
    rows: list[str] = []
    for col in columns:
        fk_html = build_fk_html(col, table_names)
        rows.append(
            "<tr>"
            f"<td>{html.escape(col.name)}</td>"
            f"<td>{html.escape(col.sql_type)}</td>"
            f"<td>{'YES' if col.is_primary_key else ''}</td>"
            f"<td>{fk_html}</td>"
            f"<td>{html.escape(col.description)}</td>"
            "</tr>"
        )

    title = html.escape(table_name)
    if table_name in value_names:
        title = f'{title} <a class="values-link" href="#values-{html.escape(table_name)}">valid values</a>'

    return (
        f'<section class="table-card" id="table-{html.escape(table_name)}">'
        f"<h2>{title}</h2>"
        "<div class=\"table-wrap\">"
        "<table>"
        f"{COLUMN_HEADER_ROW}"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def value_table_html(value_table: ValueTable) -> str:
    """Render one valid-values table card from a CSV-backed ValueTable."""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in value_table.headers)
    body_rows: list[str] = []
    for row in value_table.rows:
        padded = row + [""] * max(0, len(value_table.headers) - len(row))
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in padded[: len(value_table.headers)])
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        f'<section class="table-card" id="values-{html.escape(value_table.name)}">'
        f"<h2>{html.escape(value_table.name)} values</h2>"
        "<div class=\"table-wrap\">"
        "<table>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def build_overview_svg() -> str:
    """Build a static SVG overview of key CDM table relationships."""
    # Derived from graphviz/cdm_schematic_simple.gv core relationships.
    nodes = [
        ("header_table", 140, 50, 230, 52, "header_table", "Header / source"),
        ("observations_table", 450, 50, 250, 52, "observations_table", "Observed parameter / sensor"),
        ("station_configuration", 40, 200, 240, 44, "station_configuration", "many-to-one from header"),
        ("profile_configuration", 300, 200, 240, 44, "profile_configuration", "many-to-one from header"),
        ("source_configuration", 560, 200, 240, 44, "source_configuration", "many-to-one from header"),
        ("sensor_configuration", 820, 200, 230, 44, "sensor_configuration", "many-to-one from observations"),
        ("qc_table", 380, 300, 150, 40, "qc_table", "one-to-many from observations"),
        ("uncertainty_table", 550, 300, 180, 40, "uncertainty_table", "one-to-many from observations"),
        ("homogenisation_table", 750, 300, 220, 40, "homogenisation_table", "one-to-many from observations"),
    ]

    edges = [
        ("header_table", "observations_table", "1:N"),
        ("header_table", "station_configuration", "N:1"),
        ("header_table", "profile_configuration", "N:1"),
        ("header_table", "source_configuration", "N:1"),
        ("observations_table", "sensor_configuration", "N:1"),
        ("observations_table", "qc_table", "1:N"),
        ("observations_table", "uncertainty_table", "1:N"),
        ("observations_table", "homogenisation_table", "1:N"),
    ]

    pos = {name: (x, y, w, h, label, sub) for name, x, y, w, h, label, sub in nodes}

    def bottom_mid(name: str) -> tuple[int, int]:
        x, y, w, h, _, _ = pos[name]
        return x + w // 2, y + h

    def top_mid(name: str) -> tuple[int, int]:
        x, y, w, _, _, _ = pos[name]
        return x + w // 2, y

    def left_mid(name: str) -> tuple[int, int]:
        x, y, _, h, _, _ = pos[name]
        return x, y + h // 2

    line_parts: list[str] = []
    for src, dst, rel in edges:
        x1, y1 = bottom_mid(src)
        if src == "header_table" and dst == "observations_table":
            x2, y2 = left_mid(dst)
        else:
            x2, y2 = top_mid(dst)
        line_parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="edge" marker-end="url(#arrow)" />')

    node_parts: list[str] = []
    for name, x, y, w, h, label, sub_label in nodes:
        node_class = "node"
        target = f"#table-{name}"
        node_parts.append(
            f'<a href="{target}">'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" ry="5" class="{node_class}" />'
            f'<text x="{x + 8}" y="{y + 18}" class="node-title">{html.escape(label)}</text>'
            f'<text x="{x + 8}" y="{y + 31}" class="node-sub">{sub_label}</text>'
            "</a>"
        )

    return (
        '<section class="table-card" id="schema-overview">'
        "<h2>Schema Overview</h2>"
        '<div class="diagram-wrap">'
        '<svg viewBox="0 0 1100 360" role="img" aria-label="CDM schema overview diagram">'
        "<defs>"
        '<marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
        '<path d="M0,0 L10,4 L0,8 z" fill="#64748b" />'
        "</marker>"
        "</defs>"
        f"{''.join(line_parts)}"
        f"{''.join(node_parts)}"
        "</svg>"
        "</div>"
        "</section>"
    )


def build_html(table_map: dict[str, list[Column]], value_tables: dict[str, ValueTable]) -> str:
    """Assemble the final standalone HTML schema explorer document."""
    names = sorted(table_map.keys())
    value_names = sorted(value_tables.keys())
    table_name_set = set(names)
    value_name_set = set(value_names)

    main_nav = "".join(f'<li><a href="#table-{html.escape(name)}">{html.escape(name)}</a></li>' for name in names)
    value_nav = "".join(f'<li><a href="#values-{html.escape(name)}">{html.escape(name)} values</a></li>' for name in value_names)
    nav = (
        '<li><a href="#schema-overview"><strong>Schema Overview</strong></a></li>'
        + "<li style=\"margin-top:8px;\"><strong>Schema tables</strong></li>"
        + main_nav
        + "<li style=\"margin-top:8px;\"><strong>Valid values</strong></li>"
        + value_nav
    )
    cards = "".join(table_card_html(name, table_map[name], table_name_set, value_name_set) for name in names)
    value_cards = "".join(value_table_html(value_tables[name]) for name in value_names)
    overview = build_overview_svg()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CDM SQL Schema Explorer</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: Inter, Arial, sans-serif; margin: 0; background: #f6f7f9; color: #1f2937; }}
    .layout {{ display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }}
    nav {{ padding: 16px; background: #111827; color: #e5e7eb; position: sticky; top: 0; height: 100vh; overflow: auto; }}
    nav h1 {{ font-size: 16px; margin: 0 0 12px 0; }}
    nav ul {{ list-style: none; margin: 0; padding: 0; }}
    nav li a {{ color: #d1d5db; text-decoration: none; display: block; padding: 6px 0; font-size: 14px; }}
    nav li strong {{ color: #f9fafb; font-size: 13px; }}
    main {{ padding: 20px; }}
    .table-card {{ background: #fff; border: 1px solid #d1d5db; border-radius: 8px; margin-bottom: 16px; padding: 16px; }}
    .table-card h2 {{ margin: 0 0 10px 0; font-size: 20px; }}
    .values-link {{ font-size: 13px; margin-left: 8px; font-weight: normal; }}
    pre {{ background: #0f172a; color: #e2e8f0; border-radius: 6px; padding: 12px; overflow: auto; }}
    .table-wrap {{ overflow: auto; }}
    .diagram-wrap {{ overflow: auto; border: 1px solid #d1d5db; border-radius: 8px; padding: 8px; background: #fff; }}
    svg {{ width: 100%; height: auto; min-width: 920px; }}
    .edge {{ stroke: #64748b; stroke-width: 1.6; fill: none; }}
    .node {{ fill: #f8fafc; stroke: #475569; stroke-width: 1.2; }}
    .node-title {{ font-size: 14px; fill: #0f172a; font-weight: 600; font-family: Inter, Arial, sans-serif; }}
    .node-sub {{ font-size: 11px; fill: #475569; font-family: Inter, Arial, sans-serif; }}
    a:hover .node {{ fill: #eef2ff; stroke: #1d4ed8; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 900px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; vertical-align: top; font-size: 13px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    @media (max-width: 1000px) {{
      .layout {{ grid-template-columns: 1fr; }}
      nav {{ position: static; height: auto; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <nav>
      <h1>CDM SQL Schema</h1>
      <ul>{nav}</ul>
    </nav>
    <main>{overview}{cards}{value_cards}</main>
  </div>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for input schema directory and output HTML file."""
    parser = argparse.ArgumentParser(description="Generate SQL schema explorer HTML from table definition CSV files.")
    parser.add_argument(
        "--input-dir",
        default="table_definitions",
        help="Directory containing table definition CSV files (default: table_definitions).",
    )
    parser.add_argument(
        "--output",
        default="schema_explorer.html",
        help="Output HTML file path (default: schema_explorer.html).",
    )
    return parser.parse_args()


def resolve_path(raw_path: str, repo_root: Path) -> Path:
    """Resolve CLI path relative to repo root unless already absolute."""
    path = Path(raw_path)
    return path if path.is_absolute() else repo_root / path


def is_schema_table_csv(file_name: str) -> bool:
    """Include only schema definition files and skip helper/value CSV variants."""
    return not file_name.endswith(SKIPPED_TABLE_SUFFIXES)


def main() -> None:
    """Entry point: load CSV sources, render HTML, and write the output file."""
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    input_dir = resolve_path(args.input_dir, repo_root)
    output_file = resolve_path(args.output, repo_root)
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory not found: {input_dir}")

    value_dir = repo_root / "tables"
    if not value_dir.exists() or not value_dir.is_dir():
        raise SystemExit(f"Values directory not found: {value_dir}")

    table_map: dict[str, list[Column]] = {}
    for csv_file in sorted(input_dir.glob(CSV_GLOB)):
        if not is_schema_table_csv(csv_file.name):
            continue
        table_map[csv_file.stem] = read_table_definition(csv_file)

    if not table_map:
        raise SystemExit(f"No CSV files found in: {input_dir}")

    value_tables: dict[str, ValueTable] = {}
    for csv_path in sorted(value_dir.glob(CSV_GLOB)):
        value_table = read_value_table(csv_path)
        if value_table is not None:
            value_tables[value_table.name] = value_table

    output_file.write_text(build_html(table_map, value_tables), encoding="utf-8")
    print(f"Wrote {output_file}")


if __name__ == "__main__":
    main()
