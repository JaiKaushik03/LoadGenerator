"""Stream city interval JSONL into split-sheet XLSX without downsampling."""

import argparse
import json
from pathlib import Path
import zipfile
import hashlib
import tempfile
from contextlib import ExitStack
from xml.sax.saxutils import escape

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def records(path, group):
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            common = {k: r[k] for k in ["start_s", "end_s", "dt_s"]}
            items = [r["city"]] if group == "city" else r[group]
            for item in items:
                yield {**common, **item}


def column(n):
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def cell(ref, value):
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = "".join(c for c in str(value) if c in "\t\n\r" or ord(c) >= 32)
    if len(text) > 32767:
        raise ValueError("Text exceeds Excel cell limit; JSONL remains authoritative")
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def prepare_tables(run, folder, expected_hash=None):
    """Parse the full dataset once; spool narrow tables with bounded memory."""
    run, folder = Path(run), Path(folder)
    columns = {g: [] for g in ["city", "nodes", "assets", "ties"]}
    paths = {group: folder / (group + ".jsonl") for group in columns}
    seen = {group: set() for group in columns}
    digest = hashlib.sha256()
    with ExitStack() as stack:
        writers = {
            g: stack.enter_context(p.open("x", encoding="utf-8"))
            for g, p in paths.items()
        }
        with (run / "intervals.jsonl").open("rb") as data:
            for raw in data:
                digest.update(raw)
                record = json.loads(raw)
                common = {k: record[k] for k in ["start_s", "end_s", "dt_s"]}
                for group in columns:
                    items = [record["city"]] if group == "city" else record[group]
                    for item in items:
                        row = {**common, **item}
                        for key in row:
                            if key not in seen[group]:
                                seen[group].add(key)
                                columns[group].append(key)
                        writers[group].write(
                            json.dumps(row, allow_nan=False, separators=(",", ":"))
                            + "\n"
                        )
    if expected_hash and digest.hexdigest() != expected_hash:
        raise ValueError("Dataset checksum mismatch; export aborted")
    return columns, paths, digest.hexdigest()


def table_rows(path):
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def metadata_rows(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from metadata_rows(
                item, prefix + "." + str(key) if prefix else str(key)
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from metadata_rows(item, f"{prefix}[{index}]")
    else:
        yield {"key": prefix, "value": value}


def export_xlsx(run, target, row_limit=1_048_576):
    run, target = Path(run), Path(target)
    if not 2 <= row_limit <= 1_048_576:
        raise ValueError("Invalid worksheet row limit")
    meta = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    if meta["status"] != "complete":
        raise ValueError("Only complete runs can be exported")
    with tempfile.TemporaryDirectory(prefix="tables-", dir=run) as folder:
        columns, paths, digest = prepare_tables(run, folder, meta.get("dataset_sha256"))
        result = write_book(meta, target, row_limit, columns, paths)
        result["dataset_sha256"] = digest
        return result


def write_book(meta, target, row_limit, columns, paths):
    sheets, counts = [], {}
    with (
        target.open("xb") as dest,
        zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z,
    ):

        def write_group(group, rows, headers):
            handle = None
            number = 0
            part = 0
            total = 0

            def write_row(values, index):
                xml = (
                    f'<row r="{index}">'
                    + "".join(
                        cell(f"{column(i)}{index}", v) for i, v in enumerate(values, 1)
                    )
                    + "</row>"
                )
                handle.write(xml.encode("utf-8"))

            try:
                for row in rows:
                    if handle is None or number >= row_limit:
                        if handle:
                            handle.write(b"</sheetData></worksheet>")
                            handle.close()
                        part += 1
                        sheets.append(f"{group}_{part}")
                        handle = z.open(
                            f"xl/worksheets/sheet{len(sheets)}.xml",
                            "w",
                            force_zip64=True,
                        )
                        handle.write(
                            f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{NS}"><sheetData>'.encode()
                        )
                        number = 1
                        write_row(headers, number)
                    number += 1
                    write_row([row.get(key) for key in headers], number)
                    total += 1
            finally:
                if handle:
                    handle.write(b"</sheetData></worksheet>")
                    handle.close()
            counts[group] = total

        write_group(
            "metadata",
            metadata_rows(meta),
            ["key", "value"],
        )
        for group in columns:
            write_group(group, table_rows(paths[group]), columns[group])
        z.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(
                f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
                for i, name in enumerate(sheets, 1)
            )
            + "</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{REL}">'
            + "".join(
                f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + "</Relationships>",
        )
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + "</Types>",
        )
    return {"sheets": sheets, "records": counts, "path": str(target)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(export_xlsx(a.run, a.output), indent=2))
