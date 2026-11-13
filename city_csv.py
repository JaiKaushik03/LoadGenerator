"""Verified, bounded-memory CSV tables for a completed mission dataset."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import tempfile
from city_export import prepare_tables, table_rows
from hypergrid.checkpoints import atomic_json


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(run, output):
    run, output = Path(run), Path(output)
    meta = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    if meta["status"] != "complete":
        raise ValueError("Only complete mission runs can be exported")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "running",
        "tables": {},
        "formula_like_text": "escaped with a leading apostrophe; numeric values preserved",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="csv-tables-", dir=run) as temp:
            columns, paths, digest = prepare_tables(
                run, temp, meta.get("dataset_sha256")
            )
            manifest["source_dataset_sha256"] = digest
            for group, headers in columns.items():
                target = output / (group + ".csv")
                count = 0
                with target.open("x", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    for row in table_rows(paths[group]):
                        writer.writerow([safe_cell(row.get(key)) for key in headers])
                        count += 1
                h = hashlib.sha256()
                with target.open("rb") as f:
                    while block := f.read(1048576):
                        h.update(block)
                manifest["tables"][group] = {
                    "rows": count,
                    "sha256": h.hexdigest(),
                    "file": target.name,
                }
        atomic_json(output / "source_metadata.json", meta)
        manifest["status"] = "complete"
    except BaseException as e:
        manifest.update(status="failed", error=type(e).__name__)
        raise
    finally:
        atomic_json(output / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(export_csv(args.run, args.output), indent=2))
