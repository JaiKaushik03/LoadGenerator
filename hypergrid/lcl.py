"""Balanced averaged LCL inverter with dq voltage/current PI control.

The physical filter and cascaded-control structure follow the framework in
NREL/CP-5D00-88117; implementation is independent, with declared gains and
back-calculation anti-windup. No PWM switching or semiconductor loss model.
"""

import copy
import cmath
import math
from .emt import EMTNetwork, default_network
from .energy import finite


def default_lcl_network():
    c = default_network()
    c["step_s"] = 0.000005
    c["nodes"][0]["lcl"] = {
        "filter_c_f": 0.00002,
        "grid_l_h": 0.00065,
        "grid_r_ohm": 0.05,
        "voltage_kp_a_v": 0.02,
        "voltage_ki_a_vs": 5.0,
        "current_kp_v_a": 10.0,
        "current_ki_v_as": 1000.0,
        "antiwindup_per_s": 100.0,
        "current_reference_limit_a": 50.0,
    }
    return c


class LCLNetwork(EMTNetwork):
    WIDTH = 17

    def __init__(self, config):
        original = copy.deepcopy(config)
        base = copy.deepcopy(config)
        allowed = {
            "filter_c_f",
            "grid_l_h",
            "grid_r_ohm",
            "voltage_kp_a_v",
            "voltage_ki_a_vs",
            "current_kp_v_a",
            "current_ki_v_as",
            "antiwindup_per_s",
            "current_reference_limit_a",
        }
        for node in base["nodes"]:
            settings = node.pop("lcl", None)
            if not isinstance(settings, dict) or set(settings) != allowed:
                raise ValueError(
                    "Every LCL node must supply all supported lcl parameters"
                )
            for key, value in settings.items():
                finite(key, value, 1e-12)
            rate = max(
                1 / math.sqrt(node["source_l_h"] * settings["filter_c_f"]),
                1 / math.sqrt(settings["grid_l_h"] * settings["filter_c_f"]),
                1 / math.sqrt(settings["grid_l_h"] * node["bus_c_f"]),
                settings["grid_r_ohm"] / settings["grid_l_h"],
                settings["current_kp_v_a"] / node["source_l_h"],
                math.sqrt(settings["current_ki_v_as"] / node["source_l_h"]),
                settings["voltage_kp_a_v"] / settings["filter_c_f"],
                math.sqrt(settings["voltage_ki_a_vs"] / settings["filter_c_f"]),
                settings["antiwindup_per_s"],
            )
            if base["step_s"] * rate > 0.1:
                raise ValueError(
                    "LCL control/filter timescales require a smaller timestep"
                )
        super().__init__(base)
        old = self.initial
        self.config = original
        self.initial = []
        for j, node in enumerate(original["nodes"]):
            e = math.sqrt(2) * node["voltage_phase_rms_v"]
            self.initial += old[j * 9 : j * 9 + 9] + [
                e,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ]
        self.initial += old[9 * len(original["nodes"]) :]

    def bridge(self, node, y, k):
        settings = node["lcl"]
        theta = y[k]
        rotation = cmath.exp(1j * theta)
        angular, _, _, requested = self.primary(node, y[k : k + 5])
        i1 = complex(y[k + 5], y[k + 6])
        vc = complex(y[k + 9], y[k + 10])
        i2 = complex(y[k + 11], y[k + 12])
        i1dq = i1 / rotation
        vcdq = vc / rotation
        i2dq = i2 / rotation
        voltage_error = complex(max(0.0, requested), 0.0) - vcdq
        iv = complex(y[k + 13], y[k + 14])
        ii = complex(y[k + 15], y[k + 16])
        iref_raw = (
            i2dq
            + 1j * angular * settings["filter_c_f"] * vcdq
            + settings["voltage_kp_a_v"] * voltage_error
            + iv
        )
        scale = min(
            1.0, settings["current_reference_limit_a"] / max(abs(iref_raw), 1e-30)
        )
        iref = iref_raw * scale
        current_error = iref - i1dq
        uraw = (
            vcdq
            + node["source_r_ohm"] * i1dq
            + 1j * angular * node["source_l_h"] * i1dq
            + settings["current_kp_v_a"] * current_error
            + ii
        )
        u = uraw * rotation
        u *= min(1.0, (node["dc_voltage_v"] / 2) / max(abs(u), 1e-30))
        power = 1.5 * (u * i1.conjugate()).real
        if power > 0 and "source_power_limit_w" in node:
            u *= min(1.0, node["source_power_limit_w"] / power)
        if power < 0 and "sink_power_limit_w" in node:
            u *= min(1.0, node["sink_power_limit_w"] / (-power))
        if not node.get("source_enabled", True):
            u = 0j
        ivdot = settings["voltage_ki_a_vs"] * voltage_error + settings[
            "antiwindup_per_s"
        ] * (iref - iref_raw)
        iidot = settings["current_ki_v_as"] * current_error + settings[
            "antiwindup_per_s"
        ] * (u / rotation - uraw)
        return u, ivdot, iidot, abs(iref), abs(uraw)

    def rhs_and_powers(self, t, y):
        out = [0.0] * len(y)
        exchange = [0j for _ in self.config["nodes"]]
        node_powers = []
        resistive_loss = 0.0
        offset = len(self.config["nodes"]) * self.WIDTH
        for j, (a, b, line) in enumerate(self.lines):
            k = offset + 2 * j
            current = complex(y[k], y[k + 1])
            closed, resistance = self.line_mode(line, t)
            resistive_loss += 1.5 * resistance * abs(current) ** 2
            if closed:
                exchange[a] += line.get("ratio_a", 1.0) * current
                exchange[b] -= line.get("ratio_b", 1.0) * current
            va = complex(y[a * self.WIDTH + 7], y[a * self.WIDTH + 8])
            vb = complex(y[b * self.WIDTH + 7], y[b * self.WIDTH + 8])
            derivative = (
                (
                    line.get("ratio_a", 1.0) * va - line.get("ratio_b", 1.0) * vb
                    if closed
                    else 0j
                )
                - resistance * current
            ) / line["l_h"]
            out[k], out[k + 1] = derivative.real, derivative.imag
        for j, node in enumerate(self.config["nodes"]):
            k = j * self.WIDTH
            s = node["lcl"]
            i1 = complex(y[k + 5], y[k + 6])
            vbus = complex(y[k + 7], y[k + 8])
            vc = complex(y[k + 9], y[k + 10])
            i2 = complex(y[k + 11], y[k + 12])
            power = 1.5 * vbus * i2.conjugate()
            angular, out[k + 1], out[k + 2], _ = self.primary(node, y[k : k + 5])
            out[k] = angular
            out[k + 3] = node["power_filter_rad_s"] * (power.real - y[k + 3])
            out[k + 4] = node["power_filter_rad_s"] * (power.imag - y[k + 4])
            u, ivdot, iidot, _, _ = self.bridge(node, y, k)
            node_powers.append(
                (
                    1.5 * (u * i1.conjugate()).real,
                    1.5 * abs(vbus) ** 2 / node["load_r_ohm"],
                )
            )
            resistive_loss += 1.5 * (
                node["source_r_ohm"] * abs(i1) ** 2 + s["grid_r_ohm"] * abs(i2) ** 2
            )
            derivatives = [
                (u - vc - node["source_r_ohm"] * i1) / node["source_l_h"],
                (i2 - vbus / node["load_r_ohm"] - exchange[j]) / node["bus_c_f"],
                (i1 - i2) / s["filter_c_f"],
                (vc - vbus - s["grid_r_ohm"] * i2) / s["grid_l_h"],
                ivdot,
                iidot,
            ]
            for start, value in zip([5, 7, 9, 11, 13, 15], derivatives):
                out[k + start], out[k + start + 1] = value.real, value.imag
        return tuple(out), node_powers, resistive_loss

    def diagnostics(self, t, y):
        dy = self.rhs(t, y)
        records = []
        input_power = loss = load = energy = rate = 0.0
        for j, node in enumerate(self.config["nodes"]):
            k = j * self.WIDTH
            s = node["lcl"]
            u, _, _, iref, raw_v = self.bridge(node, y, k)
            i1 = complex(y[k + 5], y[k + 6])
            v = complex(y[k + 7], y[k + 8])
            vc = complex(y[k + 9], y[k + 10])
            i2 = complex(y[k + 11], y[k + 12])
            pin = 1.5 * (u * i1.conjugate()).real
            pload = 1.5 * abs(v) ** 2 / node["load_r_ohm"]
            ploss = 1.5 * (
                node["source_r_ohm"] * abs(i1) ** 2 + s["grid_r_ohm"] * abs(i2) ** 2
            )
            stored = 0.0
            change = 0.0
            for start, coefficient in [
                (5, node["source_l_h"]),
                (7, node["bus_c_f"]),
                (9, s["filter_c_f"]),
                (11, s["grid_l_h"]),
            ]:
                stored += (
                    0.75 * coefficient * (y[k + start] ** 2 + y[k + start + 1] ** 2)
                )
                change += (
                    1.5
                    * coefficient
                    * (
                        y[k + start] * dy[k + start]
                        + y[k + start + 1] * dy[k + start + 1]
                    )
                )
            input_power += pin
            load += pload
            loss += ploss
            energy += stored
            rate += change
            record = {
                "node": node["id"],
                "voltage_phase_rms_v": abs(v) / math.sqrt(2),
                "current_peak_a": abs(i1),
                "grid_current_peak_a": abs(i2),
                "filter_capacitor_peak_v": abs(vc),
                "controller_frequency_hz": dy[k] / (2 * math.pi),
                "bus_instantaneous_frequency_hz": (
                    v.real * dy[k + 8] - v.imag * dy[k + 7]
                )
                / (2 * math.pi * abs(v) ** 2)
                if abs(v) > 1e-6
                else None,
                "input_power_w": pin,
                "load_power_w": pload,
                "coupling_loss_w": ploss,
                "stored_energy_j": stored,
                "current_reference_peak_a": iref,
                "voltage_command_unlimited_peak_v": raw_v,
                "filtered_p_w": y[k + 3],
                "filtered_q_var": y[k + 4],
            }
            for prefix, value, unit in [("voltage", v, "v"), ("current", i2, "a")]:
                record.update(
                    {
                        f"{prefix}_alpha_{unit}": value.real,
                        f"{prefix}_beta_{unit}": value.imag,
                        f"{prefix}_a_{unit}": value.real,
                        f"{prefix}_b_{unit}": -value.real / 2
                        + math.sqrt(3) * value.imag / 2,
                        f"{prefix}_c_{unit}": -value.real / 2
                        - math.sqrt(3) * value.imag / 2,
                    }
                )
            records.append(record)
        offset = len(self.config["nodes"]) * self.WIDTH
        lines = []
        for j, (_, _, line) in enumerate(self.lines):
            k = offset + 2 * j
            i = y[k]
            q = y[k + 1]
            closed, resistance = self.line_mode(line, t)
            ploss = 1.5 * resistance * (i * i + q * q)
            loss += ploss
            energy += 0.75 * line["l_h"] * (i * i + q * q)
            lines.append(
                {
                    "tie": line["id"],
                    "a": line["a"],
                    "b": line["b"],
                    "closed": closed,
                    "current_alpha_a": i,
                    "current_beta_a": q,
                    "current_peak_a": math.hypot(i, q),
                    "resistive_loss_w": ploss,
                    "inductor_energy_j": 0.75 * line["l_h"] * (i * i + q * q),
                }
            )
            rate += 1.5 * line["l_h"] * (i * dy[k] + q * dy[k + 1])
        return {
            "time_s": t,
            "nodes": records,
            "lines": lines,
            "input_power_w": input_power,
            "load_power_w": load,
            "resistive_loss_w": loss,
            "stored_energy_j": energy,
            "power_balance_residual_w": input_power - loss - load - rate,
        }


def network_model(config):
    if any("lcl" in node for node in config["nodes"]):
        return LCLNetwork(config)
    return EMTNetwork(config)
