"""Bounded visual preview; full-resolution JSONL remains authoritative."""

import json
import math
from pathlib import Path


def preview(run, limit=400):
    path = Path(run)
    meta = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    count = meta.get("interval_records", meta.get("records", 0))
    stride = max(1, math.ceil(count / limit))
    points = []
    with (path / "intervals.jsonl").open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index % stride and index != count - 1:
                continue
            r = json.loads(line)
            if "city" in r:
                c = r["city"]
                p = {
                    "time_s": r["end_s"],
                    "supply_kw": c["actual_generation_kw"],
                    "load_kw": c["served_kw"],
                    "unserved_kw": c["unserved_kw"],
                }
            elif meta["mode"] == "emt":
                p = {
                    "time_s": r["time_s"],
                    "supply_kw": sum(n["input_power_w"] for n in r["nodes"]) / 1000,
                    "load_kw": sum(n["load_power_w"] for n in r["nodes"]) / 1000,
                }
            else:
                p = {
                    "time_s": r["end_s"],
                    "supply_kw": sum(n["mean_port_kw"] for n in r["nodes"]),
                    "load_kw": sum(n["mean_load_kw"] for n in r["nodes"]),
                }
            points.append(p)
    return {
        "points": points,
        "sampling": "uniform-stride display preview; may omit short events",
        "stride": stride,
        "full_records": count,
        "power_unit": "kW",
        "time_unit": "s",
    }
