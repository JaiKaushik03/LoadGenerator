from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .config import normalize_config

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

with open(DATA_DIR / "battery_catalog.json", "r", encoding="utf-8") as f:
    BATTERY_CATALOG = json.load(f)
with open(DATA_DIR / "semiconductor_catalog.json", "r", encoding="utf-8") as f:
    SEMICONDUCTOR_CATALOG = json.load(f)


@dataclass
class BatteryDerived:
    name: str
    ns: int
    np_: int
    nominal_voltage_v: float
    capacity_ah: float
    nominal_energy_kwh: float
    manufacturer_continuous_current_a: float
    requested_power_limit_kw: float
    hard_current_limit_a: float
    initial_soc: float
    initial_temp_c: float
    initial_soh: float
    min_soc: float
    max_soc: float
    cell_nominal_voltage_v: float
    cell_capacity_ah: float
    cell_mass_kg: float
    cell_r0_ohm: float
    cell_r1_ohm: float
    cell_r2_ohm: float
    tau1_s: float
    tau2_s: float
    cp_j_per_kgk: float
    temp_coeff_below_25_per_c: float
    temp_coeff_above_25_per_c: float
    thermal_ua_w_per_k: float
    coolant_temp_c: float
    cable_r_ohm: float
    cable_l_h: float
    contactor_fuse_r_ohm: float
    l_converter_h: float
    l_total_h: float
    inductor_r_ohm: float
    total_series_r_external_ohm: float


def _interp(x: float, xp: list[float], fp: list[float]) -> float:
    if x <= xp[0]:
        return float(fp[0])
    if x >= xp[-1]:
        return float(fp[-1])
    for k in range(len(xp) - 1):
        if xp[k] <= x <= xp[k + 1]:
            a = (x - xp[k]) / (xp[k + 1] - xp[k])
            return float(fp[k] + a * (fp[k + 1] - fp[k]))
    return float(fp[-1])


def _material_props(material: str) -> tuple[float, float]:
    if material == "aluminum":
        return 2.826e-8, 0.00403
    return 1.7241e-8, 0.00393


def cable_rl(cable: dict) -> tuple[float, float, float]:
    rho20, alpha = _material_props(str(cable.get("material", "copper")))
    conductor_temp = float(cable.get("conductor_temperature_c", 45.0))
    rho_t = rho20 * (1.0 + alpha * (conductor_temp - 20.0))
    area_m2 = float(cable.get("conductor_area_mm2", 240.0)) * 1e-6 * max(1, int(cable.get("parallel_conductors_per_polarity", 4)))
    length = float(cable.get("one_way_length_m", 5.0))
    r = rho_t * (2.0 * length) / max(area_m2, 1e-12)
    contactor_fuse = (float(cable.get("contactor_resistance_uohm", 80.0)) + float(cable.get("fuse_resistance_uohm", 40.0))) * 1e-6

    geometry = cable.get("geometry", "two_wire")
    custom_l = cable.get("custom_loop_inductance_uh_per_m")
    if geometry == "custom" and custom_l is not None:
        l_per_m = float(custom_l) * 1e-6
    elif geometry == "busbar":
        l_per_m = 0.30e-6
    else:
        mu0 = 4.0 * math.pi * 1e-7
        radius = max(float(cable.get("conductor_equivalent_radius_mm", 8.74)) * 1e-3, 1e-5)
        spacing = max(float(cable.get("conductor_spacing_mm", 45.0)) * 1e-3, 2.01 * radius)
        l_per_m = (mu0 / math.pi) * math.acosh(spacing / (2.0 * radius))
    return r, l_per_m * length, contactor_fuse


def derive_batteries(cfg: dict) -> tuple[list[BatteryDerived], list[str]]:
    warnings: list[str] = []
    out: list[BatteryDerived] = []
    fsw = float(cfg["converter"]["switching_frequency_hz"])
    target_bus = float(cfg["simulation"]["dc_bus_target_v"])

    for b in cfg["batteries"]:
        if not b.get("enabled", True):
            continue
        key = b.get("catalog_key", "hithium_314ah_lfp")
        if key not in BATTERY_CATALOG:
            raise ValueError(f"Unknown battery catalog key: {key}")
        cat = BATTERY_CATALOG[key]
        cell_v = float(cat["nominal_voltage_v"])
        cell_ah = float(cat["nominal_capacity_ah"])
        if b.get("sizing_mode") == "direct_pack":
            ns = max(1, round(float(b["direct_nominal_voltage_v"]) / cell_v))
            np_ = max(1, round(float(b["direct_capacity_ah"]) / cell_ah))
        else:
            ns = max(1, int(b["series_cells"]))
            np_ = max(1, int(b["parallel_cells"]))

        vnom = ns * cell_v
        cap = np_ * cell_ah
        en = vnom * cap / 1000.0
        cont_i = float(cat["nominal_continuous_discharge_rate_p"]) * cell_ah * np_
        p_limit_kw = float(b["requested_power_limit_kw"])
        hard_i = float(b["hard_current_limit_a"])
        if p_limit_kw * 1000.0 / max(vnom, 1.0) > cont_i * 1.02:
            warnings.append(f"{b['name']}: requested {p_limit_kw:.0f} kW exceeds the manufacturer's nominal continuous 0.5P current at nominal voltage ({cont_i:.0f} A).")
        if hard_i > cont_i * 1.05:
            warnings.append(f"{b['name']}: hard current limit {hard_i:.0f} A is above the manufacturer's nominal continuous current ({cont_i:.0f} A); treat this region as short-duration/override operation.")

        r_cable, l_cable, r_contact = cable_rl(b["cable"])
        current_nom = max(1.0, p_limit_kw * 1000.0 / max(vnom, 1.0))
        ripple = current_nom * float(cfg["converter"]["target_inductor_ripple_pct"]) / 100.0
        d_boost = max(0.05, min(0.90, 1.0 - vnom / max(target_bus, 1.0)))
        if cfg["converter"].get("inductor_mode") == "manual":
            l_conv = float(cfg["converter"]["manual_inductance_mh"]) * 1e-3
        else:
            l_conv = vnom * d_boost / max(ripple * fsw, 1e-9)
        r_ind = float(cfg["converter"]["inductor_esr_mohm"]) * 1e-3

        seed = cat["ecm_seed"]
        if b.get("ecm_source") == "manual":
            r0 = float(b["manual_r0_cell_mohm"]) * 1e-3
            r1 = float(b["manual_r1_cell_mohm"]) * 1e-3
            r2 = float(b["manual_r2_cell_mohm"]) * 1e-3
            tau1 = float(b["manual_tau1_s"])
            tau2 = float(b["manual_tau2_s"])
            cp = float(b["manual_specific_heat_j_per_kgk"])
            tc_below = float(b["manual_temp_coeff_below_25_per_c"])
            tc_above = float(b["manual_temp_coeff_above_25_per_c"])
        else:
            r0 = float(seed["r0_cell_ohm_25c"])
            r1 = float(seed["r1_cell_ohm_25c"])
            r2 = float(seed["r2_cell_ohm_25c"])
            tau1 = float(seed["tau1_s"])
            tau2 = float(seed["tau2_s"])
            cp = float(seed["specific_heat_j_per_kgk"])
            tc_below = float(seed["temp_resistance_coefficient_per_c_below_25"])
            tc_above = float(seed["temp_resistance_coefficient_per_c_above_25"])

        out.append(BatteryDerived(
            name=str(b["name"]), ns=ns, np_=np_, nominal_voltage_v=vnom, capacity_ah=cap,
            nominal_energy_kwh=en, manufacturer_continuous_current_a=cont_i,
            requested_power_limit_kw=p_limit_kw, hard_current_limit_a=hard_i,
            initial_soc=float(b["initial_soc"]), initial_temp_c=float(b["initial_temperature_c"]),
            initial_soh=float(b["initial_soh"]), min_soc=float(b["min_soc"]), max_soc=float(b["max_soc"]),
            cell_nominal_voltage_v=cell_v, cell_capacity_ah=cell_ah, cell_mass_kg=float(cat["mass_kg"]),
            cell_r0_ohm=r0, cell_r1_ohm=r1, cell_r2_ohm=r2, tau1_s=tau1, tau2_s=tau2,
            cp_j_per_kgk=cp, temp_coeff_below_25_per_c=tc_below, temp_coeff_above_25_per_c=tc_above,
            thermal_ua_w_per_k=float(b["thermal_ua_w_per_k"]), coolant_temp_c=float(b["coolant_temperature_c"]),
            cable_r_ohm=r_cable, cable_l_h=l_cable, contactor_fuse_r_ohm=r_contact,
            l_converter_h=l_conv,
            l_total_h=l_conv + (l_cable if cfg["simulation"].get("include_wire_inductance", True) else 0.0),
            inductor_r_ohm=r_ind, total_series_r_external_ohm=r_cable + r_contact + r_ind,
        ))
    return out, warnings


def _res_temp_factor(t_c: float, below: float, above: float) -> float:
    return math.exp(below * (25.0 - t_c)) if t_c < 25.0 else math.exp(-above * (t_c - 25.0))


def _soc_res_factor(soc: float) -> float:
    low = max(0.0, (0.18 - soc) / 0.18)
    high = max(0.0, (soc - 0.92) / 0.08)
    return 1.0 + 1.2 * low * low + 0.6 * high * high


def _vdrop(i_abs: float, i_ref: float, v_ref: float, diode: bool = False) -> float:
    if i_abs <= 1e-12 or v_ref <= 0:
        return 0.0
    frac = min(i_abs / max(i_ref, 1.0), 2.0)
    knee = min(1.00 if diode else 1.20, (0.60 if diode else 0.65) * v_ref)
    return knee + (v_ref - knee) * frac


def _load_power_at(t: float, schedule: list[dict]) -> float:
    value = float(schedule[0]["power_kw"]) * 1000.0
    for step in schedule:
        if t >= float(step["start_s"]):
            value = float(step["power_kw"]) * 1000.0
        else:
            break
    return value


def _share_weights(mode: str, batteries: list[BatteryDerived], soc: list[float], trip: list[int], p_req: float, custom: list[float]) -> list[float]:
    n = len(batteries)
    w = [0.0] * n
    for j, b in enumerate(batteries):
        if trip[j] != 0:
            continue
        if mode == "equal":
            w[j] = 1.0
        elif mode == "soc_weighted":
            if p_req >= 0:
                usable = max(0.0, (soc[j] - b.min_soc) / max(1e-6, 1.0 - b.min_soc))
            else:
                usable = max(0.0, (b.max_soc - soc[j]) / max(1e-6, b.max_soc))
            w[j] = b.requested_power_limit_kw * 1000.0 * (0.15 + 0.85 * usable)
        elif mode == "custom":
            w[j] = max(0.0, float(custom[j])) if j < len(custom) else 0.0
        else:
            w[j] = b.requested_power_limit_kw * 1000.0
    return w


def simulate(raw_cfg: dict) -> dict[str, Any]:
    cfg = normalize_config(raw_cfg)
    batteries, warnings = derive_batteries(cfg)
    n = len(batteries)
    if n == 0:
        raise ValueError("No enabled batteries.")

    sim = cfg["simulation"]
    conv = cfg["converter"]
    control = cfg["control"]
    protection = cfg["protections"]
    semi_key = conv["semiconductor_key"]
    if semi_key not in SEMICONDUCTOR_CATALOG:
        raise ValueError(f"Unknown semiconductor: {semi_key}")
    semi = SEMICONDUCTOR_CATALOG[semi_key]

    # Pure-Python explicit switching fidelity. Extreme resolves each PWM period at 100 integration points.
    substeps_map = {"preview": 10, "high": 25, "research": 50, "extreme": 100}
    substeps = substeps_map.get(sim.get("accuracy", "high"), 25)
    fsw = float(conv["switching_frequency_hz"])
    period = 1.0 / fsw
    dt = period / substeps
    duration = float(sim["duration_s"])
    n_steps = int(duration / dt) + 1
    requested_output_dt = 1.0 / float(sim["output_sample_rate_hz"])
    sample_every = max(1, round(requested_output_dt / dt))

    target_bus = float(sim["dc_bus_target_v"])
    vbus = float(sim["initial_bus_voltage_v"])
    bus_c = float(conv["bus_capacitance_mf"]) * 1e-3
    bus_esr = float(conv["bus_capacitor_esr_mohm"]) * 1e-3
    soft_start = float(sim["soft_start_duration_s"])
    ambient = float(sim["ambient_temperature_c"])
    deadtime = float(conv["deadtime_us"]) * 1e-6
    duty_min, duty_max = float(conv["duty_min"]), float(conv["duty_max"])
    omega_i = 2.0 * math.pi * float(conv["controller_current_bandwidth_hz"])
    omega_v = 2.0 * math.pi * float(conv["controller_voltage_bandwidth_hz"])
    parallel_modules = max(1, int(conv["parallel_switch_modules"]))
    switching_loss_scale = float(conv.get("switching_loss_scale", 1.0))

    schedule = cfg["load"]["schedule"]
    min_bus_for_cpl = float(cfg["load"]["minimum_bus_voltage_for_cpl_v"])

    # OCV table is currently shared by catalog family. Each battery can later own an independently identified HPPC map.
    ocv_cat = BATTERY_CATALOG[cfg["batteries"][0]["catalog_key"]]["ocv_calibration"]
    ocv_soc = [float(x) for x in ocv_cat["soc"]]
    ocv_charge = [float(x) for x in ocv_cat["charge_v"]]
    ocv_discharge = [float(x) for x in ocv_cat["discharge_v"]]

    sc_t = [float(x) for x in semi["vce_sat"]["temperature_c"]]
    sc_vce = [float(x) for x in semi["vce_sat"]["voltage_v"]]
    sc_vf = [_interp(t, [float(x) for x in semi["diode_vf"]["temperature_c"]], [float(x) for x in semi["diode_vf"]["voltage_v"]]) for t in sc_t]
    sc_eon = [_interp(t, [float(x) for x in semi["switching_energy"]["temperature_c"]], [float(x) for x in semi["switching_energy"]["eon_j"]]) for t in sc_t]
    sc_eoff = [_interp(t, [float(x) for x in semi["switching_energy"]["temperature_c"]], [float(x) for x in semi["switching_energy"]["eoff_j"]]) for t in sc_t]
    sc_i_ref = float(semi["switching_energy"]["i_ref_a"])
    sc_v_ref = float(semi["switching_energy"]["v_ref_v"])
    sc_tj_max = float(semi["tj_max_c"])
    sc_rth = float(semi["thermal"]["rth_jc_k_per_w"]) + float(semi["thermal"]["rth_ch_k_per_w"])
    sc_cth = max(float(semi["thermal"]["junction_thermal_capacitance_j_per_k"]), 1e-6)
    is_mosfet = "MOSFET" in str(semi.get("technology", ""))

    # State vectors.
    soc = [b.initial_soc for b in batteries]
    temp = [b.initial_temp_c for b in batteries]
    soh = [b.initial_soh for b in batteries]
    vp1 = [0.0] * n
    vp2 = [0.0] * n
    hys = [0.0] * n
    iL = [0.0] * n
    tj = [b.initial_temp_c for b in batteries]
    duty = [0.5] * n
    int_i = [0.0] * n
    int_v = 0.0
    iref = [0.0] * n
    psw_avg = [0.0] * n
    ibus_cycle_accum = [0.0] * n
    ibus_cycle_avg = [0.0] * n
    trip = [0] * n
    trip_time = [-1.0] * n
    over_i_time = [0.0] * n
    bus_uv_time = 0.0
    e_bat_discharge = [0.0] * n
    e_bus_from_battery = [0.0] * n
    e_switch_loss = [0.0] * n
    e_conduction_loss = [0.0] * n
    e_external_loss = [0.0] * n
    fade_per_cycle = 0.35 / 13000.0

    # Output columns. 2-D signals are stored row-major for direct JSON/Excel use.
    s = {
        "time_s": [], "bus_voltage_v": [], "load_power_w": [],
        "battery_current_a": [], "battery_voltage_v": [], "battery_power_w": [],
        "soc": [], "temperature_c": [], "soh": [], "current_reference_a": [],
        "duty_high": [], "gate_high": [], "gate_low": [],
        "bus_current_from_converter_a": [], "bus_current_cycle_avg_a": [],
        "switching_loss_w": [], "conduction_loss_w": [], "external_copper_loss_w": [],
        "junction_temperature_c": [],
    }

    # Scratch vectors reused in the loop.
    r0_now = [0.0] * n
    r1_now = [0.0] * n
    r2_now = [0.0] * n
    ocv_cell = [0.0] * n
    vbat = [0.0] * n
    gate_hi = [0.0] * n
    gate_lo = [0.0] * n
    ibus_each = [0.0] * n
    pcond_each = [0.0] * n
    pcopper_each = [0.0] * n
    p_req = 0.0

    for step in range(n_steps):
        t = step * dt
        p_load = _load_power_at(t, schedule)

        # Electrochemical state-dependent properties.
        for j, b in enumerate(batteries):
            ocv_c = _interp(soc[j], ocv_soc, ocv_charge)
            ocv_d = _interp(soc[j], ocv_soc, ocv_discharge)
            ocv_mid = 0.5 * (ocv_c + ocv_d)
            ocv_span = 0.5 * (ocv_c - ocv_d)
            target_h = -1.0 if iL[j] > 1.0 else (1.0 if iL[j] < -1.0 else 0.0)
            hys[j] += dt * (target_h - hys[j]) / 120.0
            ocv_cell[j] = ocv_mid + hys[j] * ocv_span
            tf = _res_temp_factor(temp[j], b.temp_coeff_below_25_per_c, b.temp_coeff_above_25_per_c)
            sf = _soc_res_factor(soc[j])
            health = max(soh[j], 0.55)
            r0_now[j] = b.cell_r0_ohm * tf * sf / health
            r1_now[j] = b.cell_r1_ohm * tf * sf / health
            r2_now[j] = b.cell_r2_ohm * tf * sf / health
            i_cell = iL[j] / b.np_
            vbat[j] = b.ns * (ocv_cell[j] - i_cell * r0_now[j] - vp1[j] - vp2[j])

        # Digital controller updates synchronously at the PWM frequency.
        if step % substeps == 0:
            vref = (float(sim["initial_bus_voltage_v"]) + min(1.0, t / max(soft_start, 1e-12)) * (target_bus - float(sim["initial_bus_voltage_v"]))) if soft_start > 0 and t < soft_start else target_bus
            mode = control.get("mode", "dc_bus_voltage")
            if mode == "dc_bus_voltage":
                verr = vref - vbus
                kp_v = bus_c * max(vref, 100.0) * omega_v
                ki_v = kp_v * omega_v / 4.0
                p_unsat = p_load + kp_v * verr + int_v
                total_limit = sum(b.requested_power_limit_kw * 1000.0 for j, b in enumerate(batteries) if trip[j] == 0)
                p_req = min(max(p_unsat, -total_limit), total_limit)
                if abs(p_req - p_unsat) < 1e-6 or (p_req >= total_limit and verr < 0) or (p_req <= -total_limit and verr > 0):
                    int_v += ki_v * verr * period
            elif mode == "power":
                p_req = float(control.get("fixed_power_kw", 500.0)) * 1000.0
            else:
                p_req = 0.0

            weights = _share_weights(control.get("power_sharing", "rated_power"), batteries, soc, trip, p_req, control.get("custom_shares", []))
            wsum = sum(weights) or 1.0

            for j, b in enumerate(batteries):
                if trip[j] != 0:
                    iref[j] = 0.0
                    duty[j] = 0.5
                    psw_avg[j] = 0.0
                    continue
                if mode == "current":
                    iref[j] = float(control.get("fixed_current_a", 500.0)) * weights[j] / wsum
                else:
                    p_j = p_req * weights[j] / wsum
                    iref[j] = p_j / max(abs(vbat[j]), 50.0)
                if soc[j] <= b.min_soc and iref[j] > 0:
                    iref[j] = 0.0
                if soc[j] >= b.max_soc and iref[j] < 0:
                    iref[j] = 0.0
                iref[j] = min(max(iref[j], -b.hard_current_limit_a), b.hard_current_limit_a)

                dff = min(max(vbat[j] / max(vbus, 100.0), duty_min), duty_max)
                kp_i = b.l_total_h * omega_i / max(vbus, 100.0)
                ki_i = max(b.total_series_r_external_ohm, 1e-5) * omega_i / max(vbus, 100.0)
                ierr = iref[j] - iL[j]
                u = kp_i * ierr + int_i[j]
                d_unsat = dff - u
                d_cmd = min(max(d_unsat, duty_min), duty_max)
                if abs(d_cmd - d_unsat) < 1e-9 or (d_cmd >= duty_max and ierr > 0) or (d_cmd <= duty_min and ierr < 0):
                    int_i[j] += ki_i * ierr * period
                duty[j] = d_cmd

                if sim.get("include_switching_losses", True):
                    i_module = abs(iL[j]) / parallel_modules
                    eon_ref = _interp(tj[j], sc_t, sc_eon)
                    eoff_ref = _interp(tj[j], sc_t, sc_eoff)
                    i_scale = (i_module / max(sc_i_ref, 1.0)) ** 1.05
                    v_scale = (max(vbus, 50.0) / max(sc_v_ref, 1.0)) ** 1.10
                    e_device = (eon_ref + eoff_ref) * i_scale * v_scale
                    psw_avg[j] = 2.0 * parallel_modules * e_device * fsw * switching_loss_scale
                else:
                    psw_avg[j] = 0.0

        phase = (step % substeps) * dt
        total_bus_current = 0.0
        for j, b in enumerate(batteries):
            gate_hi[j] = gate_lo[j] = ibus_each[j] = pcond_each[j] = pcopper_each[j] = 0.0
            if trip[j] != 0:
                iL[j] = 0.0
                continue

            high_end = duty[j] * period
            dt_dead = min(deadtime, 0.45 * period)
            hi_on = phase >= 0.5 * dt_dead and phase < max(0.5 * dt_dead, high_end - 0.5 * dt_dead)
            lo_on = phase >= min(period, high_end + 0.5 * dt_dead) and phase < period - 0.5 * dt_dead
            gate_hi[j] = 1.0 if hi_on else 0.0
            gate_lo[j] = 1.0 if lo_on else 0.0

            iabs = abs(iL[j])
            vce_ref = _interp(tj[j], sc_t, sc_vce)
            vf_ref = _interp(tj[j], sc_t, sc_vf)
            vce = _vdrop(iabs / parallel_modules, sc_i_ref, vce_ref, False)
            vf = _vdrop(iabs / parallel_modules, sc_i_ref, vf_ref, True)

            if hi_on:
                if is_mosfet:
                    vnode = vbus + vce if iL[j] >= 0 else vbus - vce
                    pcond = vce * iabs
                else:
                    if iL[j] >= 0:
                        vnode, pcond = vbus + vf, vf * iabs
                    else:
                        vnode, pcond = vbus - vce, vce * iabs
                ibus = iL[j]
            elif lo_on:
                if is_mosfet:
                    vnode = vce if iL[j] >= 0 else -vce
                    pcond = vce * iabs
                else:
                    if iL[j] >= 0:
                        vnode, pcond = vce, vce * iabs
                    else:
                        vnode, pcond = -vf, vf * iabs
                ibus = 0.0
            else:
                if iL[j] >= 0:
                    vnode, pcond, ibus = vbus + vf, vf * iabs, iL[j]
                else:
                    vnode, pcond, ibus = -vf, vf * iabs, 0.0

            i_cell = iL[j] / b.np_
            vp1[j] += dt * ((r1_now[j] * i_cell - vp1[j]) / max(b.tau1_s, 1e-9))
            vp2[j] += dt * ((r2_now[j] * i_cell - vp2[j]) / max(b.tau2_s, 1e-9))
            vbat_j = b.ns * (ocv_cell[j] - i_cell * r0_now[j] - vp1[j] - vp2[j])
            di = (vbat_j - vnode - b.total_series_r_external_ohm * iL[j]) / max(b.l_total_h, 1e-9)
            iL[j] += dt * di

            sw_loss_i = psw_avg[j] / max(vbus, 100.0)
            ibus_adj = ibus - sw_loss_i
            ibus_each[j] = ibus_adj
            total_bus_current += ibus_adj
            ibus_cycle_accum[j] += ibus_adj
            pcond_each[j] = pcond
            pcopper_each[j] = iL[j] * iL[j] * b.total_series_r_external_ohm

            p_bat = vbat_j * iL[j]
            p_bus = vbus * ibus_adj
            if p_bat > 0:
                e_bat_discharge[j] += p_bat * dt
            e_bus_from_battery[j] += p_bus * dt
            e_switch_loss[j] += psw_avg[j] * dt
            e_conduction_loss[j] += pcond * dt
            e_external_loss[j] += pcopper_each[j] * dt

            soc[j] -= dt * i_cell / (max(b.cell_capacity_ah * soh[j], 1e-9) * 3600.0)
            soc[j] = min(max(soc[j], 0.0), 1.0)
            if sim.get("include_aging", True):
                dcycles = abs(i_cell) * dt / (2.0 * max(b.cell_capacity_ah, 1e-9) * 3600.0)
                temp_stress = math.exp(0.025 * max(0.0, temp[j] - 25.0))
                c_rate = abs(i_cell) / max(b.cell_capacity_ah, 1e-9)
                rate_stress = 1.0 + 0.18 * max(0.0, c_rate - 0.5) ** 1.3
                soh[j] = max(0.50, soh[j] - fade_per_cycle * dcycles * temp_stress * rate_stress)

            if sim.get("include_thermal", True):
                n_cells = b.ns * b.np_
                q_cell = i_cell * i_cell * r0_now[j]
                q_cell += vp1[j] * vp1[j] / max(r1_now[j], 1e-12)
                q_cell += vp2[j] * vp2[j] / max(r2_now[j], 1e-12)
                q_total = n_cells * q_cell
                cth_bat = n_cells * b.cell_mass_kg * b.cp_j_per_kgk
                temp[j] += dt * (q_total - b.thermal_ua_w_per_k * (temp[j] - b.coolant_temp_c)) / max(cth_bat, 1.0)
                p_pair = pcond + psw_avg[j]
                p_device = p_pair / max(2.0 * parallel_modules, 1.0)
                if sc_rth > 0:
                    tj[j] += dt * (p_device - (tj[j] - ambient) / sc_rth) / sc_cth
                else:
                    tj[j] = ambient

            if abs(iL[j]) > b.hard_current_limit_a:
                over_i_time[j] += dt
            else:
                over_i_time[j] = max(0.0, over_i_time[j] - 2.0 * dt)

            if protection.get("enabled", True) and trip[j] == 0:
                code = 0
                if over_i_time[j] >= float(protection["current_trip_delay_ms"]) * 1e-3:
                    code = 1
                elif temp[j] >= float(protection["battery_overtemperature_c"]):
                    code = 2
                elif tj[j] >= min(float(protection["semiconductor_overtemperature_c"]), sc_tj_max):
                    code = 3
                elif soc[j] <= b.min_soc - 0.002:
                    code = 4
                elif soc[j] >= b.max_soc + 0.002:
                    code = 5
                if code:
                    trip[j], trip_time[j] = code, t

        if (step + 1) % substeps == 0:
            for j in range(n):
                ibus_cycle_avg[j] = ibus_cycle_accum[j] / substeps
                ibus_cycle_accum[j] = 0.0

        if abs(p_load) < 1.0:
            i_load = 0.0
        elif vbus >= min_bus_for_cpl:
            i_load = p_load / max(vbus, 1.0)
        else:
            fold = max(0.0, vbus / max(min_bus_for_cpl, 1.0))
            i_load = (p_load / max(min_bus_for_cpl, 1.0)) * fold

        i_cap = total_bus_current - i_load
        p_cap_esr = i_cap * i_cap * bus_esr
        i_esr_loss = p_cap_esr / max(vbus, 100.0)
        vbus += dt * (total_bus_current - i_load - i_esr_loss) / max(bus_c, 1e-9)
        vbus = max(0.0, vbus)

        if protection.get("enabled", True) and t > soft_start:
            if vbus < float(protection["bus_undervoltage_v"]):
                bus_uv_time += dt
            else:
                bus_uv_time = 0.0
            global_trip = vbus > float(protection["bus_overvoltage_v"]) or bus_uv_time > float(protection["bus_undervoltage_delay_s"])
            if global_trip:
                for j in range(n):
                    if trip[j] == 0:
                        trip[j] = 6 if vbus > float(protection["bus_overvoltage_v"]) else 7
                        trip_time[j] = t

        if step % sample_every == 0 or step == n_steps - 1:
            vbat_row, ibat_row, pbat_row = [], [], []
            for j, b in enumerate(batteries):
                i_cell = iL[j] / b.np_
                vb = b.ns * (ocv_cell[j] - i_cell * r0_now[j] - vp1[j] - vp2[j])
                vbat_row.append(vb); ibat_row.append(iL[j]); pbat_row.append(vb * iL[j])
            s["time_s"].append(t); s["bus_voltage_v"].append(vbus); s["load_power_w"].append(p_load)
            s["battery_current_a"].append(ibat_row); s["battery_voltage_v"].append(vbat_row); s["battery_power_w"].append(pbat_row)
            s["soc"].append(soc.copy()); s["temperature_c"].append(temp.copy()); s["soh"].append(soh.copy()); s["current_reference_a"].append(iref.copy())
            s["duty_high"].append(duty.copy()); s["gate_high"].append(gate_hi.copy()); s["gate_low"].append(gate_lo.copy())
            s["bus_current_from_converter_a"].append(ibus_each.copy()); s["bus_current_cycle_avg_a"].append(ibus_cycle_avg.copy())
            s["switching_loss_w"].append(psw_avg.copy()); s["conduction_loss_w"].append(pcond_each.copy()); s["external_copper_loss_w"].append(pcopper_each.copy()); s["junction_temperature_c"].append(tj.copy())

    trip_labels = {0: "none", 1: "battery overcurrent", 2: "battery overtemperature", 3: "semiconductor overtemperature", 4: "minimum SOC", 5: "maximum SOC", 6: "DC bus overvoltage", 7: "DC bus undervoltage"}
    start_metric = max(soft_start, 0.1)
    errors = [v - target_bus for t, v in zip(s["time_s"], s["bus_voltage_v"]) if t >= start_metric]
    bus_rmse = math.sqrt(sum(x*x for x in errors) / len(errors)) if errors else float("nan")
    bus_max_dev = max((abs(x) for x in errors), default=float("nan"))

    batt_summaries = []
    for j, b in enumerate(batteries):
        col_i = [row[j] for row in s["battery_current_a"]]
        col_v = [row[j] for row in s["battery_voltage_v"]]
        col_t = [row[j] for row in s["temperature_c"]]
        col_tj = [row[j] for row in s["junction_temperature_c"]]
        col_psw = [row[j] for row in s["switching_loss_w"]]
        col_pcond = [row[j] for row in s["conduction_loss_w"]]
        eff = e_bus_from_battery[j] / e_bat_discharge[j] if e_bat_discharge[j] > 0 else None
        batt_summaries.append({
            **asdict(b),
            "max_current_a": max((abs(x) for x in col_i), default=0.0),
            "min_terminal_voltage_v": min(col_v), "max_terminal_voltage_v": max(col_v),
            "final_soc_pct": 100.0 * soc[j], "max_temperature_c": max(col_t), "max_junction_temperature_c": max(col_tj),
            "peak_switching_loss_kw": max(col_psw) / 1000.0, "peak_conduction_loss_kw": max(col_pcond) / 1000.0,
            "estimated_discharge_efficiency": eff,
            "discharge_energy_from_battery_j": e_bat_discharge[j], "energy_delivered_to_bus_j": e_bus_from_battery[j],
            "switching_loss_energy_j": e_switch_loss[j], "conduction_loss_energy_j": e_conduction_loss[j], "external_copper_loss_energy_j": e_external_loss[j],
            "trip": trip_labels.get(trip[j], "unknown"), "trip_time_s": None if trip_time[j] < 0 else trip_time[j],
        })

    warnings.extend([
        "The public cell OCV curve is provisional rather than a manufacturer HPPC map.",
        "R1/R2/tau ECM dynamics are engineering seed parameters until HPPC/EIS identification data are supplied; HyperGrid intentionally preserves this provenance instead of presenting them as measured cell-specific truth.",
        "Portable v0.2 uses the same physical states in a zero-dependency pure-Python explicit-PWM solver. Use Research or Extreme fidelity when resolving switching ripple for analysis.",
    ])

    return {
        "run_id": uuid.uuid4().hex[:12],
        "config": cfg,
        "warnings": warnings,
        "derived": {"time_step_s": dt, "switching_substeps": substeps, "output_sample_every_steps": sample_every, "battery_count": n, "batteries": [asdict(b) for b in batteries]},
        "summary": {
            "bus_target_v": target_bus, "bus_min_v": min(s["bus_voltage_v"]), "bus_max_v": max(s["bus_voltage_v"]), "bus_final_v": s["bus_voltage_v"][-1],
            "bus_rmse_after_softstart_v": bus_rmse, "bus_max_abs_deviation_after_softstart_v": bus_max_dev,
            "peak_load_kw": max(s["load_power_w"]) / 1000.0, "battery_summaries": batt_summaries,
        },
        "series": s,
    }


def jsonify_result(result: dict[str, Any], max_points: int = 8000) -> dict[str, Any]:
    """Return a browser-sized copy while keeping the full run in server memory for Excel export."""
    s = result["series"]
    n = len(s["time_s"])
    stride = max(1, math.ceil(n / max_points))
    if stride == 1:
        return result
    slim = {k: v[::stride] for k, v in s.items()}
    out = dict(result)
    out["series"] = slim
    out["browser_downsample_stride"] = stride
    return out
