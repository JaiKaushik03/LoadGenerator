from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _flatten(obj: Any, prefix: str = ""):
    rows = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            rows.extend(_flatten(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            rows.extend(_flatten(v, f"{prefix}[{i}]"))
    else:
        rows.append((prefix, obj))
    return rows


def _col_name(n: int) -> str:
    n += 1
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _cell(ref: str, value: Any, style: int = 0) -> str:
    if value is None:
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" s="{style}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f'<c r="{ref}" s="{style}"><v>{float(value):.15g}</v></c>'
    txt = escape(str(value))
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{txt}</t></is></c>'


def _sheet_xml(rows: list[list[Any]], widths: list[float] | None = None, header_rows: set[int] | None = None) -> str:
    header_rows = header_rows or set()
    cols = ""
    if widths:
        parts = []
        for i, w in enumerate(widths, start=1):
            parts.append(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
        cols = "<cols>" + "".join(parts) + "</cols>"
    xml_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row):
            style = 1 if (r_idx - 1) in header_rows else 0
            cells.append(_cell(f"{_col_name(c_idx)}{r_idx}", value, style))
        xml_rows.append(f'<row r="{r_idx}">' + "".join(cells) + "</row>")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'{cols}<sheetData>{"".join(xml_rows)}</sheetData>'
        '</worksheet>'
    )


def export_xlsx(result: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets: list[tuple[str, str]] = []

    summary = result["summary"]
    rows = [
        ["HyperGrid Battery-to-Local-DC-Bus Simulation", ""],
        ["Run ID", result["run_id"]],
        ["Metric", "Value"],
    ]
    for key in ["bus_target_v", "bus_min_v", "bus_max_v", "bus_final_v", "bus_rmse_after_softstart_v", "bus_max_abs_deviation_after_softstart_v", "peak_load_kw"]:
        rows.append([key, summary[key]])
    rows.append([])
    rows.append(["Warnings / provenance", ""])
    for w in result.get("warnings", []):
        rows.append(["Warning", w])
    rows.append([])
    rows.append(["Battery summaries", ""])
    for i, b in enumerate(summary["battery_summaries"], start=1):
        rows.append([f"Battery {i}", b["name"]])
        for f in ["nominal_voltage_v", "capacity_ah", "nominal_energy_kwh", "manufacturer_continuous_current_a", "requested_power_limit_kw", "hard_current_limit_a", "max_current_a", "min_terminal_voltage_v", "max_terminal_voltage_v", "final_soc_pct", "max_temperature_c", "max_junction_temperature_c", "peak_switching_loss_kw", "peak_conduction_loss_kw", "estimated_discharge_efficiency", "trip", "trip_time_s"]:
            rows.append([f, b.get(f)])
        rows.append([])
    sheets.append(("Summary", _sheet_xml(rows, [42, 90], {2})))

    rows = [["Parameter", "Value"]]
    for k, v in _flatten(result["config"]):
        rows.append([k, v if not isinstance(v, (dict, list)) else json.dumps(v)])
    sheets.append(("Configuration", _sheet_xml(rows, [66, 42], {0})))

    rows = [["Derived quantity", "Value"]]
    for k, v in _flatten(result["derived"]):
        rows.append([k, v if not isinstance(v, (dict, list)) else json.dumps(v)])
    sheets.append(("Derived Model", _sheet_xml(rows, [62, 38], {0})))

    s = result["series"]
    nrows = len(s["time_s"])
    max_rows = 1_000_000
    stride = max(1, math.ceil(nrows / max_rows))
    rows = [["time_s", "bus_voltage_v", "load_power_w"]]
    for k in range(0, nrows, stride):
        rows.append([s["time_s"][k], s["bus_voltage_v"][k], s["load_power_w"][k]])
    sheets.append(("System Time Series", _sheet_xml(rows, [18, 20, 20], {0})))

    nbat = len(summary["battery_summaries"])
    headers = [
        "time_s", "battery_voltage_v", "battery_current_a", "battery_power_w", "soc", "temperature_c", "soh",
        "current_reference_a", "duty_high", "gate_high", "gate_low", "bus_current_instantaneous_a", "bus_current_cycle_avg_a",
        "switching_loss_w", "conduction_loss_w", "external_copper_loss_w", "junction_temperature_c"
    ]
    signal_keys = [
        "battery_voltage_v", "battery_current_a", "battery_power_w", "soc", "temperature_c", "soh", "current_reference_a",
        "duty_high", "gate_high", "gate_low", "bus_current_from_converter_a", "bus_current_cycle_avg_a",
        "switching_loss_w", "conduction_loss_w", "external_copper_loss_w", "junction_temperature_c"
    ]
    for j in range(nbat):
        rows = [headers]
        for k in range(0, nrows, stride):
            row = [s["time_s"][k]]
            row.extend(s[key][k][j] for key in signal_keys)
            rows.append(row)
        sheets.append((f"Battery {j+1}", _sheet_xml(rows, [16] + [20] * (len(headers)-1), {0})))

    with open(DATA_DIR / "sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)
    rows = [["Source", "URL"]] + [[name, url] for name, url in sources.items()]
    sheets.append(("Sources", _sheet_xml(rows, [34, 120], {0})))

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for i in range(len(sheets)):
        content_types.append(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    content_types.append('</Types>')

    workbook_sheets = []
    rels = []
    for i, (name, _) in enumerate(sheets, start=1):
        workbook_sheets.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
        rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
    style_rid = len(sheets) + 1
    rels.append(f'<Relationship Id="rId{style_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>' + ''.join(workbook_sheets) + '</sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(rels) + '</Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1E3A8A"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ''.join(content_types))
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", styles)
        for i, (_, xml) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
    return path
