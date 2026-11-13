"""Optional independent solver comparisons; requires requirements-validation.txt.

SciPy integrates the same published-model RHS independently. pvlib solves the
same PV equation independently. These check numerical implementation, not
component calibration, model-form error, MATLAB parity or lunar accuracy.
"""

import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from scipy.integrate import solve_ivp
from pvlib.pvsystem import singlediode
from hypergrid.solar import SolarArray
from hypergrid.emt import default_network
from hypergrid.lcl import network_model, default_lcl_network


def compare():
    pv = SolarArray(60, 2, 8.0, 1e-10, 0.003, 500.0, 1.3, 0.004, 1.12)
    solar = []
    for g in [100.0, 500.0, 1000.0, 1400.0]:
        for temp in [-20.0, 25.0, 60.0]:
            ours = pv.operating_point(g, temperature_c=temp)
            iph, i0, a = pv.parameters(g, temp)
            ref = singlediode(
                iph,
                i0,
                pv.series_resistance_cell_ohm,
                pv.shunt_resistance_cell_ohm,
                a,
                method="lambertw",
            )
            reference = (
                float(ref["p_mp"]) * pv.series_cells * pv.parallel_strings / 1000
            )
            solar.append(
                {
                    "irradiance_w_m2": g,
                    "temperature_c": temp,
                    "hypergrid_mpp_kw": ours["array_power_kw"],
                    "pvlib_mpp_kw": reference,
                    "relative_power_error": abs(ours["array_power_kw"] - reference)
                    / reference,
                }
            )
    electrical = []
    for topology, factory in [("rl", default_network), ("lcl", default_lcl_network)]:
        for control in ["droop", "vsm", "dvoc"]:
            c = factory()
            c["duration_s"] = 0.04
            c["nodes"][0]["control"] = control
            model = network_model(c)
            rows = list(model.samples())
            times = [r["time_s"] for r in rows]
            ref = solve_ivp(
                model.rhs,
                (0.0, c["duration_s"]),
                model.initial,
                method="DOP853",
                rtol=1e-10,
                atol=1e-11,
                t_eval=times,
            )
            if not ref.success:
                raise RuntimeError("Independent EMT reference failed: " + ref.message)
            magnitude_errors = []
            voltage_errors = []
            current_errors = []
            current_index = 11 if topology == "lcl" else 5
            current_scale = max(
                1.0,
                max(
                    math.hypot(ref.y[current_index, i], ref.y[current_index + 1, i])
                    for i in range(len(times))
                ),
            )
            for i, row in enumerate(rows):
                node = row["nodes"][0]
                reference = math.hypot(ref.y[7, i], ref.y[8, i]) / math.sqrt(2)
                magnitude_errors.append(abs(node["voltage_phase_rms_v"] - reference))
                voltage_errors.append(
                    math.hypot(
                        node["voltage_alpha_v"] - ref.y[7, i],
                        node["voltage_beta_v"] - ref.y[8, i],
                    )
                )
                current_errors.append(
                    math.hypot(
                        node["current_alpha_a"] - ref.y[current_index, i],
                        node["current_beta_a"] - ref.y[current_index + 1, i],
                    )
                )
            electrical.append(
                {
                    "topology": topology,
                    "control": control,
                    "samples": len(rows),
                    "step_s": c["step_s"],
                    "config": c,
                    "reference": "SciPy DOP853, same model RHS",
                    "rtol": 1e-10,
                    "atol": 1e-11,
                    "max_voltage_error_v": max(magnitude_errors),
                    "max_error_relative_to_nominal_voltage": max(magnitude_errors)
                    / c["nodes"][0]["voltage_phase_rms_v"],
                    "max_normalized_voltage_waveform_error": max(voltage_errors)
                    / (math.sqrt(2) * c["nodes"][0]["voltage_phase_rms_v"]),
                    "max_normalized_current_waveform_error": max(current_errors)
                    / current_scale,
                }
            )
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for source in [
        root / "validate_references.py",
        *sorted((root / "hypergrid").glob("*.py")),
    ]:
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    threshold = 0.01
    passed = all(r["relative_power_error"] <= threshold for r in solar) and all(
        r["max_normalized_voltage_waveform_error"] <= threshold
        and r["max_normalized_current_waveform_error"] <= threshold
        for r in electrical
    )
    return {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "source_sha256": digest.hexdigest(),
        "solar_cell_parameters": asdict(pv),
        "packages": {
            x: importlib.metadata.version(x) for x in ["numpy", "scipy", "pvlib"]
        },
        "criterion": "<=1% PV MPP relative error and <=1% normalized EMT voltage/current waveform errors on stated cases",
        "passed": passed,
        "solar_cases": solar,
        "electrical_cases": electrical,
        "limitations": [
            "Independent numerical solvers share the stated model equations and parameter inputs",
            "Not a validation of physical component parameters, full city behavior, commercial tool parity or flight suitability",
        ],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = compare()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "solar_cases": len(result["solar_cases"]),
                "electrical_cases": len(result["electrical_cases"]),
                "max_pv_relative_error": max(
                    r["relative_power_error"] for r in result["solar_cases"]
                ),
                "max_emt_normalized_error": max(
                    r["max_error_relative_to_nominal_voltage"]
                    for r in result["electrical_cases"]
                ),
            },
            indent=2,
        )
    )
    if not result["passed"]:
        raise SystemExit(1)
