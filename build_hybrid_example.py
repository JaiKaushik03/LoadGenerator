"""Create an explicit illustrative city including all five storage families."""

import json
from pathlib import Path
from hypergrid.city import default_city


def hybrid_example():
    c = default_city()
    c["parameter_provenance"] = (
        "Editable illustrative assumptions; no measured lunar or component calibration"
    )
    for index, node in enumerate(c["nodes"]):
        source = node["sources"][0]
        source["pv"] = {
            "series_cells": 60,
            "parallel_strings": 500 if index == 0 else 140,
            "photocurrent_ref_a": 8.0,
            "saturation_current_ref_a": 1e-10,
            "series_resistance_cell_ohm": 0.003,
            "shunt_resistance_cell_ohm": 500.0,
            "ideality_factor": 1.3,
            "current_temp_coefficient_a_k": 0.004,
            "bandgap_ev": 1.12,
            "cell_temperature_c": 25.0,
        }
        source["dust_transmission"] = 0.95
        source["reference_irradiance_w_m2"] = 1000.0
    n = c["nodes"][0]
    common = {
        "initial_fraction": 0.8,
        "charge_limit_kw": 20.0,
        "discharge_limit_kw": 20.0,
        "charge_efficiency": 0.8,
        "discharge_efficiency": 0.6,
        "min_fraction": 0.1,
        "max_fraction": 0.95,
        "self_discharge_per_hour": 0.0001,
    }
    n["storage"] += [
        {
            **common,
            "id": "rfc0",
            "kind": "regenerative_fuel_cell",
            "hydrogen_capacity_kg": 50.0,
            "hydrogen_specific_energy_kwh_kg": 33.33,
        },
        {
            **common,
            "id": "flywheel0",
            "kind": "flywheel",
            "inertia_kg_m2": 720.0,
            "maximum_speed_rad_s": 1000.0,
            "charge_efficiency": 0.92,
            "discharge_efficiency": 0.92,
            "self_discharge_per_hour": 0.01,
        },
        {
            **common,
            "id": "supercap0",
            "kind": "supercapacitor",
            "capacitance_f": 7200.0,
            "maximum_voltage_v": 100.0,
            "charge_efficiency": 0.98,
            "discharge_efficiency": 0.98,
            "self_discharge_per_hour": 0.02,
        },
    ]
    c["nodes"][1]["thermal"] = [
        {
            "id": "habitat_heat",
            "mass_kg": 20000.0,
            "specific_heat_j_kg_k": 4180.0,
            "initial_temperature_c": 70.0,
            "ambient_c": -20.0,
            "conductance_w_k": 10.0,
            "min_temperature_c": 35.0,
            "max_temperature_c": 90.0,
            "cop": 1.0,
            "priority": 0,
            "heater_electric_kw": [
                {"time_s": 0, "value": 10.0},
                {"time_s": 43200.0, "value": 0.0},
            ],
            "demand_kw_th": [{"time_s": 0, "value": 5.0}],
        }
    ]
    c["telemetry"] = {
        "seed": 42,
        "delay_s": 0.5,
        "jitter_s": 0.1,
        "loss_probability": 0.01,
        "power_noise_std_kw": 0.01,
        "freshness_limit_s": 120.0,
        "attacks": [
            {
                "start_s": 3600.0,
                "end_s": 7200.0,
                "kind": "bias",
                "targets": ["solar0"],
                "bias_kw": 20.0,
            },
            {
                "start_s": 43200.0,
                "end_s": 46800.0,
                "kind": "drop",
                "targets": ["battery1"],
            },
        ],
    }
    return c


if __name__ == "__main__":
    target = Path("examples/city-hybrid.json")
    target.write_text(json.dumps(hybrid_example(), indent=2) + "\n", encoding="utf-8")
    print(target)
