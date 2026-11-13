"""Stream auditable mission data with verified JSON checkpoints and OS locking."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time
from hypergrid.city import CityModel, default_city
from hypergrid.energy import finite
from hypergrid.checkpoints import (
    atomic_json,
    writer_lock,
    verified_prefix,
    preserve_uncommitted_tail,
)


def source_fingerprint():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in [root / "city_cli.py", *sorted((root / "hypergrid").glob("*.py"))]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def accumulate(totals, record):
    c = record["city"]
    h = record["dt_s"] / 3600
    for key in [
        "generation",
        "actual_generation",
        "served",
        "unserved",
        "curtailed",
        "transmission_loss",
    ]:
        totals[key + "_kwh"] = (
            totals.get(key + "_kwh", 0.0) + c.get(key + "_kw", 0.0) * h
        )
    totals["storage_loss_kwh"] = (
        totals.get("storage_loss_kwh", 0.0) + c["storage_loss_kwh"]
    )
    totals["max_abs_bus_balance_residual_kw"] = max(
        totals.get("max_abs_bus_balance_residual_kw", 0.0),
        abs(c["balance_residual_kw"]),
    )
    for key in ["input_kw_th", "served_kw_th", "unserved_kw_th", "dump_kw_th"]:
        energy_key = key.replace("_kw_th", "_kwh_th")
        totals[energy_key] = totals.get(energy_key, 0.0) + c[key] * h
    for key in ["ambient_loss_kwh_th", "stored_change_kwh_th"]:
        totals[key] = totals.get(key, 0.0) + c[key]


def run(config, output, resume=False, checkpoint_every=1000):
    if (
        isinstance(checkpoint_every, bool)
        or not isinstance(checkpoint_every, int)
        or not 1 <= checkpoint_every <= 1000000
    ):
        raise ValueError("checkpoint_every must be an integer from 1 to 1000000")
    model = CityModel(config)
    output = Path(output)
    if not resume:
        output.mkdir(parents=True, exist_ok=False)
    elif not output.is_dir():
        raise ValueError("Resume directory does not exist")
    with writer_lock(output):
        return run_locked(model, config, output, resume, checkpoint_every)


def run_locked(model, config, output, resume, checkpoint_every):
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    code_hash = source_fingerprint()
    meta_path = output / "metadata.json"
    data_path = output / "intervals.jsonl"
    checkpoint_path = output / "checkpoint.json"
    rows = integration_intervals = 0
    totals = {}
    digest = hashlib.sha256()
    offset = 0
    if resume:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            checkpoint.get("schema_version") != 1
            or checkpoint.get("config_sha256") != config_hash
            or checkpoint.get("source_sha256") != code_hash
        ):
            raise ValueError(
                "Checkpoint source/configuration does not match; start a new run after code or parameter changes"
            )
        rows = checkpoint["records"]
        integration_intervals = checkpoint["integration_intervals"]
        for value in [rows, integration_intervals]:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Invalid checkpoint counters")
        totals = checkpoint["totals"]
        if not isinstance(totals, dict):
            raise ValueError("Invalid checkpoint totals")
        for value in totals.values():
            finite("checkpoint total", value, -math.inf)
        offset = checkpoint["bytes"]
        digest = verified_prefix(data_path, offset, checkpoint["prefix_sha256"])
        model.restore(checkpoint["model_state"])
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            metadata.get("source_sha256") != code_hash
            or metadata.get("config_sha256") != config_hash
        ):
            raise ValueError("Run metadata does not match checkpoint")
        tail = preserve_uncommitted_tail(data_path, offset)
        if tail:
            metadata.setdefault("preserved_uncommitted_tails", []).append(tail)
        metadata["resumed_at_utc"] = datetime.now(timezone.utc).isoformat()
    else:
        metadata = {
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "mission",
            "fidelity": "energy_balance",
            "source_sha256": code_hash,
            "config_sha256": config_hash,
            "config": config,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "limitations": [
                "Mission energy model, not a switched circuit solver or calibrated lunar digital twin",
                "Ordered direct energy transfers; use electrical mode for physical RL/LCL network transients",
                "Uniform aggregate battery state; per-cell averages do not model independent cell mismatch",
                "Optional measurement transport is not an SDN emulator or trained intrusion detector",
                "No hardware/clinical/flight validation or commercial-tool equivalence is established",
            ],
        }
    metadata.update(status="running", resumed=resume)
    atomic_json(meta_path, metadata)
    started = time.perf_counter()

    def save_checkpoint(handle):
        handle.flush()
        os.fsync(handle.fileno())
        atomic_json(
            checkpoint_path,
            {
                "schema_version": 1,
                "source_sha256": code_hash,
                "config_sha256": config_hash,
                "records": rows,
                "integration_intervals": integration_intervals,
                "totals": totals,
                "bytes": offset,
                "prefix_sha256": digest.hexdigest(),
                "model_state": model.snapshot(),
            },
        )

    try:
        with data_path.open("ab" if resume else "xb") as f:
            if not resume:
                save_checkpoint(f)
            for record in model.outputs():
                encoded = (
                    json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n"
                ).encode("utf-8")
                f.write(encoded)
                digest.update(encoded)
                offset += len(encoded)
                rows += 1
                integration_intervals += record["integration_intervals"]
                accumulate(totals, record)
                if rows % checkpoint_every == 0:
                    save_checkpoint(f)
            save_checkpoint(f)
        metadata.update(
            status="complete",
            interval_records=rows,
            integration_intervals=integration_intervals,
            totals=totals,
            dataset_sha256=digest.hexdigest(),
            completed_time_s=model.elapsed_s,
            output_sampling={
                "power_fields": "time-weighted interval means",
                "energy_deltas": "summed",
                "stored_states": "end of output interval",
                "telemetry": "final integration interval",
                "coincident_time_tolerance": "max(1e-12 s, 8 ULP at current time)",
            },
        )
    except BaseException as e:
        metadata.update(
            status="failed", completed_interval_records=rows, error=type(e).__name__
        )
        raise
    finally:
        metadata.update(
            runtime_s=time.perf_counter() - started,
            runtime_scope="this invocation, including checkpoint I/O",
        )
        atomic_json(meta_path, metadata)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-example", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint-every", type=int, default=1000)
    args = parser.parse_args()
    if args.write_example:
        with args.write_example.open("x", encoding="utf-8") as f:
            json.dump(default_city(), f, indent=2, allow_nan=False)
        return
    if not args.output:
        parser.error("--output is required")
    config = (
        json.loads(args.config.read_text(encoding="utf-8"))
        if args.config
        else default_city()
    )
    result = run(config, args.output, args.resume, args.checkpoint_every)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ["status", "interval_records", "runtime_s", "totals"]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
