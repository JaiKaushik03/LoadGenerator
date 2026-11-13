"""Run declared balanced EMT or two-way resource/EMT windows, with audit data."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import tempfile
import time
from datetime import datetime, timezone
from city_export import export_xlsx
from hypergrid.city import default_city
from hypergrid.emt import default_network
from hypergrid.lcl import network_model, default_lcl_network
from hypergrid.coupled import CoupledModel


def coupled_example(lcl=False):
    city = default_city()
    city["duration_s"] = 0.2
    electrical = default_network()
    template = copy.deepcopy(electrical["nodes"][0])
    electrical["nodes"] = [
        {
            **copy.deepcopy(template),
            "id": n["id"],
            "source_l_h": 0.00026,
            "source_r_ohm": 0.01,
            "p_set_w": 30000.0,
            "load_r_ohm": 1.44,
        }
        for n in city["nodes"]
    ]
    electrical["lines"] = [
        {"id": t["id"], "a": t["a"], "b": t["b"], "r_ohm": 0.2, "l_h": 0.002}
        for t in city["ties"]
    ]
    city["ties"] = []
    city["step_s"] = 0.01
    if lcl:
        electrical["step_s"] = 0.000005
        electrical["duration_s"] = city["duration_s"] = 0.1
        settings = default_lcl_network()["nodes"][0]["lcl"]
        for node in electrical["nodes"]:
            node["dc_voltage_v"] = 600.0
            node["lcl"] = {
                **settings,
                "current_kp_v_a": 5.0,
                "current_reference_limit_a": 200.0,
            }
    return {"city": city, "electrical": electrical, "resource_interval_s": 0.01}


def run(config, output, mode):
    if mode == "emt":
        model = network_model(config)
        iterator = model.samples()
    elif mode == "coupled":
        model = CoupledModel(
            config["city"], config["electrical"], config["resource_interval_s"]
        )
        iterator = model.intervals()
    else:
        raise ValueError("Mode must be emt or coupled")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for path in [
        root / "electrical_cli.py",
        *sorted((root / "hypergrid").glob("*.py")),
    ]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    meta = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "mode": mode,
        "source_sha256": digest.hexdigest(),
        "config": config,
        "config_sha256": hashlib.sha256(
            json.dumps(config, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "limitations": [
            "Balanced alpha-beta RL or cascaded-PI LCL topology as configured; averaged bridge, not semiconductor switching or UMIC hardware",
            "Resistive AC loads and ideal lossless DC/AC bridge; no semiconductor/DC converter loss prediction",
            "Primary droop/VSM/dVOC equations; no certified controller, calibrated hardware or lab validation",
            "Resource mode uses macro-interval-average port power; refine both time scales to assess coupling error",
        ],
    }
    meta_path = output / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    started = time.perf_counter()
    count = 0
    max_residual = 0.0
    final_time = 0.0
    dataset_digest = hashlib.sha256()
    try:
        with (output / "intervals.jsonl").open("xb") as f:
            for row in iterator:
                encoded = (
                    json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n"
                ).encode("utf-8")
                f.write(encoded)
                dataset_digest.update(encoded)
                count += 1
                key = (
                    "power_balance_residual_w"
                    if mode == "emt"
                    else "electrical_balance_residual_j"
                )
                max_residual = max(max_residual, abs(row[key]))
                final_time = row.get("time_s", row.get("end_s"))
        meta.update(
            status="complete",
            records=count,
            final_time_s=final_time,
            runtime_s=time.perf_counter() - started,
            maximum_balance_residual=max_residual,
            balance_residual_unit="W" if mode == "emt" else "J",
            dataset_sha256=dataset_digest.hexdigest(),
        )
    except BaseException as e:
        meta.update(status="failed", completed_records=count, error=type(e).__name__)
        raise
    finally:
        temp = meta_path.with_suffix(".tmp")
        temp.write_text(json.dumps(meta, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(meta_path)
    return meta


def export_run(run_path, target):
    """Normalize a stream for the bounded XLSX writer without altering source."""
    run_path = Path(run_path)
    meta = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    if meta["status"] != "complete":
        raise ValueError("Cannot export incomplete run")
    expected_hash = meta.pop("dataset_sha256", None)
    meta["source_dataset_sha256"] = expected_hash
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="xlsx-stage-", dir=run_path) as tmp:
        stage = Path(tmp)
        (stage / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with (
            (stage / "intervals.jsonl").open("x", encoding="utf-8") as dest,
            (run_path / "intervals.jsonl").open("rb") as src,
        ):
            previous = 0.0
            for line in src:
                digest.update(line)
                row = json.loads(line)
                assets = []
                if meta["mode"] == "emt":
                    end = row["time_s"]
                    start = previous
                    city = {
                        k: v
                        for k, v in row.items()
                        if k not in ["nodes", "lines", "time_s"]
                    }
                    nodes = row["nodes"]
                    ties = row.get("lines", [])
                else:
                    start, end = row["start_s"], row["end_s"]
                    city = {
                        k: v
                        for k, v in row.items()
                        if k not in ["nodes", "electrical", "start_s", "end_s", "dt_s"]
                    }
                    emt = {n["node"]: n for n in row["electrical"]["nodes"]}
                    ties = row["electrical"].get("lines", [])
                    nodes = []
                    for n in row["nodes"]:
                        nodes.append(
                            {
                                **emt[n["node"]],
                                **{
                                    k: v
                                    for k, v in n.items()
                                    if k not in ["storage", "loads"]
                                },
                            }
                        )
                        assets += [{"node": n["node"], **a} for a in n["storage"]]
                        assets += [{"node": n["node"], **a} for a in n["loads"]]
                dest.write(
                    json.dumps(
                        {
                            "start_s": start,
                            "end_s": end,
                            "dt_s": end - start,
                            "city": city,
                            "nodes": nodes,
                            "assets": assets,
                            "ties": ties,
                        }
                    )
                    + "\n"
                )
                previous = end
        if expected_hash and digest.hexdigest() != expected_hash:
            raise ValueError("Dataset checksum mismatch; export aborted")
        return export_xlsx(stage, target)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["emt", "coupled"], required=True)
    p.add_argument("--config", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--xlsx", action="store_true")
    a = p.parse_args()
    config = (
        json.loads(a.config.read_text(encoding="utf-8"))
        if a.config
        else (default_network() if a.mode == "emt" else coupled_example())
    )
    result = run(config, a.output, a.mode)
    if a.xlsx:
        export_run(a.output, a.output / "electrical.xlsx")
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "mode",
                    "status",
                    "records",
                    "final_time_s",
                    "runtime_s",
                    "maximum_balance_residual",
                    "balance_residual_unit",
                ]
            },
            indent=2,
        )
    )
