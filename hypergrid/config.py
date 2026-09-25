from __future__ import annotations

import copy


def default_config() -> dict:
    return {
        "system_name": "HyperGrid Battery-to-DC-Bus Test",
        "architecture": "A_individual_converter_per_battery",
        "batteries": [
            {
                "name": "Battery 1",
                "enabled": True,
                "catalog_key": "hithium_314ah_lfp",
                "chemistry": "LFP",
                "sizing_mode": "cell_architecture",
                "series_cells": 250,
                "parallel_cells": 9,
                "direct_nominal_voltage_v": 800.0,
                "direct_capacity_ah": 2826.0,
                "initial_soc": 0.80,
                "initial_temperature_c": 25.0,
                "initial_soh": 1.0,
                "requested_power_limit_kw": 1120.0,
                "hard_current_limit_a": 1500.0,
                "min_soc": 0.10,
                "max_soc": 0.95,
                "thermal_ua_w_per_k": 550.0,
                "coolant_temperature_c": 25.0,
                "cell_parameter_dispersion_pct": 1.0,
                "ecm_source": "catalog_seed",
                "manual_r0_cell_mohm": 0.20,
                "manual_r1_cell_mohm": 0.07,
                "manual_r2_cell_mohm": 0.05,
                "manual_tau1_s": 4.0,
                "manual_tau2_s": 45.0,
                "manual_specific_heat_j_per_kgk": 1000.0,
                "manual_temp_coeff_below_25_per_c": 0.025,
                "manual_temp_coeff_above_25_per_c": 0.006,
                "cable": {
                    "material": "copper",
                    "one_way_length_m": 5.0,
                    "conductor_area_mm2": 240.0,
                    "parallel_conductors_per_polarity": 4,
                    "conductor_temperature_c": 45.0,
                    "geometry": "two_wire",
                    "conductor_spacing_mm": 45.0,
                    "conductor_equivalent_radius_mm": 8.74,
                    "custom_loop_inductance_uh_per_m": None,
                    "contactor_resistance_uohm": 80.0,
                    "fuse_resistance_uohm": 40.0,
                },
            }
        ],
        "converter": {
            "semiconductor_key": "infineon_fz1500r33hl3_reference",
            "switching_frequency_hz": 2000.0,
            "deadtime_us": 5.0,
            "inductor_mode": "auto",
            "target_inductor_ripple_pct": 10.0,
            "manual_inductance_mh": 1.5,
            "inductor_esr_mohm": 1.2,
            "bus_capacitance_mf": 80.0,
            "bus_capacitor_esr_mohm": 1.5,
            "parallel_switch_modules": 1,
            "switching_loss_scale": 1.0,
            "controller_current_bandwidth_hz": 100.0,
            "controller_voltage_bandwidth_hz": 8.0,
            "duty_min": 0.05,
            "duty_max": 0.95,
        },
        "load": {
            "type": "constant_power",
            "schedule": [
                {"start_s": 0.0, "power_kw": 0.0},
                {"start_s": 0.60, "power_kw": 100.0},
                {"start_s": 1.00, "power_kw": 300.0},
                {"start_s": 1.40, "power_kw": 600.0},
                {"start_s": 1.80, "power_kw": 1000.0},
                {"start_s": 2.60, "power_kw": 450.0},
            ],
            "minimum_bus_voltage_for_cpl_v": 500.0,
        },
        "protections": {
            "enabled": True,
            "battery_overtemperature_c": 60.0,
            "semiconductor_overtemperature_c": 145.0,
            "bus_overvoltage_v": 1650.0,
            "bus_undervoltage_v": 1100.0,
            "bus_undervoltage_delay_s": 0.25,
            "current_trip_delay_ms": 5.0,
        },
        "simulation": {
            "duration_s": 3.2,
            "accuracy": "high",
            "output_sample_rate_hz": 5000.0,
            "initial_bus_voltage_v": 800.0,
            "dc_bus_target_v": 1500.0,
            "soft_start_duration_s": 0.50,
            "ambient_temperature_c": 25.0,
            "random_seed": 7,
            "include_aging": True,
            "include_thermal": True,
            "include_switching_losses": True,
            "include_wire_inductance": True,
        },
        "control": {
            "mode": "dc_bus_voltage",
            "power_sharing": "rated_power",
            "custom_shares": [],
            "fixed_power_kw": 500.0,
            "fixed_current_a": 500.0,
        },
    }


def _merge(default, supplied):
    if isinstance(default, dict) and isinstance(supplied, dict):
        out = copy.deepcopy(default)
        for key, value in supplied.items():
            if key in out:
                out[key] = _merge(out[key], value)
            else:
                out[key] = copy.deepcopy(value)
        return out
    return copy.deepcopy(supplied)


def normalize_config(supplied: dict | None) -> dict:
    cfg = _merge(default_config(), supplied or {})
    if not isinstance(cfg.get("batteries"), list) or not cfg["batteries"]:
        raise ValueError("At least one battery is required.")
    if not any(bool(b.get("enabled", True)) for b in cfg["batteries"]):
        raise ValueError("At least one battery must be enabled.")

    sim = cfg["simulation"]
    conv = cfg["converter"]
    prot = cfg["protections"]
    if float(sim["duration_s"]) <= 0 or float(sim["duration_s"]) > 120:
        raise ValueError("Simulation duration must be > 0 and <= 120 s.")
    if float(sim["dc_bus_target_v"]) <= 0:
        raise ValueError("DC bus target must be positive.")
    if float(conv["switching_frequency_hz"]) < 200 or float(conv["switching_frequency_hz"]) > 100000:
        raise ValueError("Switching frequency must be between 200 Hz and 100 kHz.")
    if not 0 <= float(conv["duty_min"]) < float(conv["duty_max"]) <= 1:
        raise ValueError("Duty limits are invalid.")
    if float(conv["bus_capacitance_mf"]) <= 0:
        raise ValueError("DC-link capacitance must be positive.")
    if float(sim["output_sample_rate_hz"]) <= 0:
        raise ValueError("Output sample rate must be positive.")
    if prot["enabled"] and float(prot["bus_undervoltage_v"]) >= float(prot["bus_overvoltage_v"]):
        raise ValueError("Bus undervoltage threshold must be below bus overvoltage threshold.")

    for i, b in enumerate(cfg["batteries"], start=1):
        if not b.get("enabled", True):
            continue
        if float(b["min_soc"]) >= float(b["max_soc"]):
            raise ValueError(f"Battery {i}: min SOC must be below max SOC.")
        if not 0 <= float(b["initial_soc"]) <= 1:
            raise ValueError(f"Battery {i}: initial SOC must be between 0 and 1.")
        if int(b["series_cells"]) < 1 or int(b["parallel_cells"]) < 1:
            raise ValueError(f"Battery {i}: series/parallel cell counts must be positive.")
        if float(b["hard_current_limit_a"]) <= 0:
            raise ValueError(f"Battery {i}: hard current limit must be positive.")

    cfg["load"]["schedule"] = sorted(cfg["load"]["schedule"], key=lambda x: float(x["start_s"]))
    return cfg
