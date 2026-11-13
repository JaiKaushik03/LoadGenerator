"""Reproduce mission and coupled runtime, output size and conservation evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_hybrid_example import hybrid_example
from city_cli import run as mission_run
from city_export import export_xlsx
from city_csv import export_csv
from electrical_cli import run as electrical_run, coupled_example, export_run


def measure(output, repeats=3):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "kind": "synthetic software benchmark; not physical validation",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "repeats": repeats,
        "cases": [],
    }
    for name, config, mode in [
        ("mission-hybrid", hybrid_example(), "mission"),
        ("coupled-lcl", coupled_example(lcl=True), "coupled"),
    ]:
        timings = []
        for repeat in range(repeats):
            folder = output / f"{name}-{repeat + 1}"
            meta = (
                mission_run(config, folder)
                if mode == "mission"
                else electrical_run(config, folder, mode)
            )
            timings.append(meta["runtime_s"])
        started = time.perf_counter()
        book = folder / "data.xlsx"
        exported = (
            export_xlsx(folder, book) if mode == "mission" else export_run(folder, book)
        )
        export_seconds = time.perf_counter() - started
        with zipfile.ZipFile(book) as archive:
            if archive.testzip() is not None:
                raise AssertionError("Corrupt workbook")
        csv_manifest = export_csv(folder, folder / "csv") if mode == "mission" else None
        case = {
            "name": name,
            "config": config,
            "mode": mode,
            "runtime_seconds": timings,
            "median_runtime_s": statistics.median(timings),
            "metadata": meta,
            "jsonl_bytes": (folder / "intervals.jsonl").stat().st_size,
            "xlsx_bytes": book.stat().st_size,
            "xlsx_export_runtime_s": export_seconds,
            "xlsx_sha256": hashlib.sha256(book.read_bytes()).hexdigest(),
            "table_records": exported["records"],
            "csv_tables": csv_manifest["tables"] if csv_manifest else None,
        }
        case["component_table_rows"] = sum(
            v for k, v in exported["records"].items() if k != "metadata"
        )
        report["cases"].append(case)
        print(
            json.dumps(
                {
                    "name": name,
                    "median_runtime_s": case["median_runtime_s"],
                    "component_table_rows": case["component_table_rows"],
                }
            ),
            flush=True,
        )
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be from 1 to 10")
    measure(args.output, args.repeats)
