"""Balanced alpha-beta EMT network with voltage sources behind physical RL.

Primary controls follow the droop/VSM/dVOC equations in NREL/CP-5D00-88117.
This is a declared reduced topology: one coupling RL and bus capacitor, not
the paper's cascaded-loop LCL converter, semiconductor switching, or UMIC.
All voltages/currents are alpha-beta phase-peak coordinates; three-phase
instantaneous power is 1.5*(v_alpha*i_alpha + v_beta*i_beta).
"""

import math
import copy
from .energy import finite
from .numerics import rk4_step


def default_network():
    return {
        "duration_s": 0.2,
        "step_s": 0.00002,
        "output_interval_s": 0.0002,
        "frequency_hz": 60.0,
        "nodes": [
            {
                "id": "habitat",
                "control": "vsm",
                "voltage_phase_rms_v": 120.0,
                "dc_voltage_v": 400.0,
                "source_l_h": 0.0026,
                "source_r_ohm": 0.1,
                "bus_c_f": 0.0002,
                "load_r_ohm": 20.0,
                "p_set_w": 2160.0,
                "q_set_var": 0.0,
                "mp_rad_s_per_w": 0.0002,
                "mq_v_per_var": 0.0001,
                "inertia_w_s2_rad": 100.0,
                "power_filter_rad_s": 50.0,
                "dvoc_k1": 5.76,
                "dvoc_k2": 0.000001,
            }
        ],
        "lines": [],
    }


class EMTNetwork:
    """State per node: theta, delta_omega, E, Pf, Qf, i_a,i_b,v_a,v_b.

    Lines add alpha/beta currents. Fixed-step RK4; no hard state clipping.
    Source amplitude is bounded by a two-level SPWM modulation envelope.
    Resistive loads are physical impedances, not constant-power approximations.
    """

    WIDTH = 9

    def __init__(self, c):
        self.config = copy.deepcopy(c)
        c = self.config

        def keys(obj, allowed, label):
            if not isinstance(obj, dict) or set(obj) - set(allowed.split()):
                raise ValueError(label + ": unsupported settings")

        keys(
            c,
            "duration_s step_s output_interval_s frequency_hz nodes lines",
            "EMT config",
        )
        finite("frequency_hz", c["frequency_hz"], 1.0, 1000.0)
        self.omega = 2 * math.pi * c["frequency_hz"]
        finite("duration_s", c["duration_s"], 1e-12, 120.0)
        finite("step_s", c["step_s"], 1e-9)
        finite("output_interval_s", c["output_interval_s"], c["step_s"])
        if c["duration_s"] / c["step_s"] > 10_000_000:
            raise ValueError("EMT step budget exceeded")
        if not c["nodes"] or len(c["nodes"]) > 100:
            raise ValueError("EMT requires 1–100 nodes")
        for n in c["nodes"]:
            keys(
                n,
                "id control voltage_phase_rms_v dc_voltage_v source_l_h source_r_ohm bus_c_f load_r_ohm p_set_w q_set_var mp_rad_s_per_w mq_v_per_var inertia_w_s2_rad power_filter_rad_s dvoc_k1 dvoc_k2 source_enabled source_power_limit_w sink_power_limit_w",
                "EMT node",
            )
            if not isinstance(n["id"], str) or not n["id"]:
                raise ValueError("EMT node ID must be a nonempty string")
        self.index = {n["id"]: j for j, n in enumerate(c["nodes"])}
        if len(self.index) != len(c["nodes"]):
            raise ValueError("Duplicate node ID")
        self.lines = []
        ids = set()
        max_rate = self.omega
        for n in c["nodes"]:
            if n["control"] not in ["droop", "vsm", "dvoc"]:
                raise ValueError("Unknown primary control")
            for key in [
                "voltage_phase_rms_v",
                "dc_voltage_v",
                "source_l_h",
                "source_r_ohm",
                "bus_c_f",
                "load_r_ohm",
                "mp_rad_s_per_w",
                "mq_v_per_var",
                "inertia_w_s2_rad",
                "power_filter_rad_s",
                "dvoc_k1",
                "dvoc_k2",
            ]:
                finite(key, n[key], 1e-12)
            finite("p_set_w", n["p_set_w"], -1e9, 1e9)
            finite("q_set_var", n["q_set_var"], -1e9, 1e9)
            if math.sqrt(2) * n["voltage_phase_rms_v"] > n["dc_voltage_v"] / 2:
                raise ValueError(
                    "Requested AC voltage exceeds SPWM DC-link capability; specify a valid converter/transformer profile"
                )
            max_rate = max(
                max_rate,
                n["source_r_ohm"] / n["source_l_h"],
                1 / math.sqrt(n["source_l_h"] * n["bus_c_f"]),
                1 / (n["load_r_ohm"] * n["bus_c_f"]),
                n["power_filter_rad_s"],
            )
            if n["control"] == "vsm":
                max_rate = max(
                    max_rate, 1 / (n["mp_rad_s_per_w"] * n["inertia_w_s2_rad"])
                )
            if n["control"] == "dvoc":
                max_rate = max(
                    max_rate,
                    4 * n["dvoc_k2"] * self.omega * n["voltage_phase_rms_v"] ** 2,
                )
            if not isinstance(n.get("source_enabled", True), bool):
                raise ValueError("source_enabled must be boolean")
            for key in ["source_power_limit_w", "sink_power_limit_w"]:
                if key in n:
                    finite(key, n[key], 0.0, 1e12)
        for line in c["lines"]:
            keys(
                line,
                "id a b r_ohm l_h closed_schedule open_snubber_r_ohm ratio_a ratio_b",
                "EMT line",
            )
            if (
                line["id"] in ids
                or line["a"] == line["b"]
                or not {line["a"], line["b"]} <= set(self.index)
            ):
                raise ValueError("Invalid EMT line")
            ids.add(line["id"])
            finite("line_r_ohm", line["r_ohm"], 0.0)
            finite("line_l_h", line["l_h"], 1e-12)
            for key in ["ratio_a", "ratio_b"]:
                finite(key, line.get(key, 1.0), 1e-6, 1e6)
            finite(
                "open_snubber_r_ohm",
                line.get("open_snubber_r_ohm", max(1.0, line["r_ohm"])),
                1e-12,
            )
            schedule = line.get("closed_schedule", [{"time_s": 0.0, "value": 1}])
            if not schedule or schedule[0]["time_s"] != 0:
                raise ValueError("Line schedule must start at zero")
            previous = -1.0
            for point in schedule:
                keys(point, "time_s value", "Line event")
                finite("time_s", point["time_s"])
                if point["time_s"] <= previous or point["value"] not in [0, 1]:
                    raise ValueError(
                        "Line schedule must increase and contain closed=0/1"
                    )
                previous = point["time_s"]
            self.lines.append((self.index[line["a"]], self.index[line["b"]], line))
            ca = c["nodes"][self.index[line["a"]]]["bus_c_f"]
            cb = c["nodes"][self.index[line["b"]]]["bus_c_f"]
            max_rate = max(
                max_rate,
                math.sqrt(
                    (
                        line.get("ratio_a", 1.0) ** 2 / ca
                        + line.get("ratio_b", 1.0) ** 2 / cb
                    )
                    / line["l_h"]
                ),
            )
            max_rate = max(
                max_rate,
                line["r_ohm"] / line["l_h"],
                line.get("open_snubber_r_ohm", max(1.0, line["r_ohm"])) / line["l_h"],
            )
        self.event_times = sorted(
            {
                p["time_s"]
                for line in c["lines"]
                for p in line.get("closed_schedule", [])
                if 0 < p["time_s"] < c["duration_s"]
            }
        )
        # Conservative explicit-solver preflight. Convergence is still tested.
        if c["step_s"] * max_rate > 0.1:
            raise ValueError("EMT step is too large for configured circuit timescales")
        self.initial = []
        for n in c["nodes"]:
            e = math.sqrt(2) * n["voltage_phase_rms_v"]
            self.initial += [0.0, 0.0, e, 0.0, 0.0, 0.0, 0.0, e, 0.0]
        self.initial += [0.0] * (2 * len(self.lines))

    def rhs(self, t, y):
        return self.rhs_and_powers(t, y)[0]

    def rhs_and_powers(self, t, y):
        out = [0.0] * len(y)
        node_powers = []
        resistive_loss = 0.0
        exchange = [[0.0, 0.0] for _ in self.config["nodes"]]
        start = len(self.config["nodes"]) * self.WIDTH
        for k, (a, b, line) in enumerate(self.lines):
            offset = start + 2 * k
            connected, resistance = self.line_mode(line, t)
            resistive_loss += 1.5 * resistance * (y[offset] ** 2 + y[offset + 1] ** 2)
            for axis in range(2):
                current = y[offset + axis]
                if connected:
                    exchange[a][axis] += line.get("ratio_a", 1.0) * current
                    exchange[b][axis] -= line.get("ratio_b", 1.0) * current
                out[offset + axis] = (
                    (
                        line.get("ratio_a", 1.0) * y[a * self.WIDTH + 7 + axis]
                        - line.get("ratio_b", 1.0) * y[b * self.WIDTH + 7 + axis]
                        if connected
                        else 0.0
                    )
                    - resistance * current
                ) / line["l_h"]
        for j, n in enumerate(self.config["nodes"]):
            k = j * self.WIDTH
            theta, dw, e, pf, qf, ia, ib, va, vb = y[k : k + self.WIDTH]
            p = 1.5 * (va * ia + vb * ib)
            q = 1.5 * (vb * ia - va * ib)
            angular, out[k + 1], out[k + 2], requested_e = self.primary(n, y[k : k + 5])
            amplitude = min(n["dc_voltage_v"] / 2, max(0.0, requested_e))
            amplitude = self.limited_amplitude(n, amplitude, theta, ia, ib)
            ua, ub = amplitude * math.cos(theta), amplitude * math.sin(theta)
            node_powers.append(
                (1.5 * (ua * ia + ub * ib), 1.5 * (va * va + vb * vb) / n["load_r_ohm"])
            )
            resistive_loss += 1.5 * n["source_r_ohm"] * (ia * ia + ib * ib)
            out[k] = angular
            out[k + 3] = n["power_filter_rad_s"] * (p - pf)
            out[k + 4] = n["power_filter_rad_s"] * (q - qf)
            out[k + 5] = (ua - va - n["source_r_ohm"] * ia) / n["source_l_h"]
            out[k + 6] = (ub - vb - n["source_r_ohm"] * ib) / n["source_l_h"]
            out[k + 7] = (ia - va / n["load_r_ohm"] - exchange[j][0]) / n["bus_c_f"]
            out[k + 8] = (ib - vb / n["load_r_ohm"] - exchange[j][1]) / n["bus_c_f"]
        return tuple(out), node_powers, resistive_loss

    def primary(self, node, state):
        _, dw, e, pf, qf = state
        e0 = math.sqrt(2) * node["voltage_phase_rms_v"]
        dw_rate = e_rate = 0.0
        if node["control"] == "vsm":
            angular = self.omega + dw
            dw_rate = (node["p_set_w"] - pf - dw / node["mp_rad_s_per_w"]) / node[
                "inertia_w_s2_rad"
            ]
            requested = e0 + node["mq_v_per_var"] * (node["q_set_var"] - qf)
        elif node["control"] == "droop":
            angular = self.omega + node["mp_rad_s_per_w"] * (node["p_set_w"] - pf)
            requested = e0 + node["mq_v_per_var"] * (node["q_set_var"] - qf)
        else:
            if e <= 1e-6:
                raise ValueError("dVOC voltage state reached its singular domain")
            angular = self.omega + node["dvoc_k1"] * (node["p_set_w"] - pf) / (e * e)
            e_rate = (
                node["dvoc_k2"] * self.omega * e * (e0 * e0 - e * e)
                + node["dvoc_k2"] * (node["q_set_var"] - qf) / e
            )
            requested = e
        return angular, dw_rate, e_rate, requested

    @staticmethod
    def line_mode(line, time_s):
        closed = True
        for point in line.get("closed_schedule", []):
            if point["time_s"] > time_s + max(
                1e-12, 8 * math.ulp(max(1.0, abs(time_s)))
            ):
                break
            closed = bool(point["value"])
        resistance = (
            line["r_ohm"]
            if closed
            else line.get("open_snubber_r_ohm", max(1.0, line["r_ohm"]))
        )
        return closed, resistance

    @staticmethod
    def limited_amplitude(node, amplitude, theta, ia, ib):
        if not node.get("source_enabled", True):
            return 0.0
        projection = 1.5 * (math.cos(theta) * ia + math.sin(theta) * ib)
        if projection > 0 and "source_power_limit_w" in node:
            amplitude = min(amplitude, node["source_power_limit_w"] / projection)
        elif projection < 0 and "sink_power_limit_w" in node:
            amplitude = min(amplitude, node["sink_power_limit_w"] / (-projection))
        return amplitude

    def diagnostics(self, t, y):
        rhs = self.rhs(t, y)
        total_input = total_loss = total_load = stored = stored_rate = 0.0
        records = []
        for j, n in enumerate(self.config["nodes"]):
            k = j * self.WIDTH
            theta, dw, e, pf, qf, ia, ib, va, vb = y[k : k + self.WIDTH]
            if n["control"] == "dvoc":
                requested = e
            else:
                requested = math.sqrt(2) * n["voltage_phase_rms_v"] + n[
                    "mq_v_per_var"
                ] * (n["q_set_var"] - qf)
            amplitude = min(n["dc_voltage_v"] / 2, max(0.0, requested))
            amplitude = self.limited_amplitude(n, amplitude, theta, ia, ib)
            p_in = 1.5 * amplitude * (math.cos(theta) * ia + math.sin(theta) * ib)
            p_loss = 1.5 * n["source_r_ohm"] * (ia * ia + ib * ib)
            p_load = 1.5 * (va * va + vb * vb) / n["load_r_ohm"]
            energy = 0.75 * (
                n["source_l_h"] * (ia * ia + ib * ib)
                + n["bus_c_f"] * (va * va + vb * vb)
            )
            rate = 1.5 * (
                n["source_l_h"] * (ia * rhs[k + 5] + ib * rhs[k + 6])
                + n["bus_c_f"] * (va * rhs[k + 7] + vb * rhs[k + 8])
            )
            total_input += p_in
            total_loss += p_loss
            total_load += p_load
            stored += energy
            stored_rate += rate
            records.append(
                {
                    "node": n["id"],
                    "voltage_phase_rms_v": math.hypot(va, vb) / math.sqrt(2),
                    "current_peak_a": math.hypot(ia, ib),
                    "controller_frequency_hz": rhs[k] / (2 * math.pi),
                    "bus_instantaneous_frequency_hz": (
                        va * rhs[k + 8] - vb * rhs[k + 7]
                    )
                    / (2 * math.pi * (va * va + vb * vb))
                    if va * va + vb * vb > 1e-12
                    else None,
                    "voltage_alpha_v": va,
                    "voltage_beta_v": vb,
                    "current_alpha_a": ia,
                    "current_beta_a": ib,
                    "voltage_a_v": va,
                    "voltage_b_v": -va / 2 + math.sqrt(3) * vb / 2,
                    "voltage_c_v": -va / 2 - math.sqrt(3) * vb / 2,
                    "current_a_a": ia,
                    "current_b_a": -ia / 2 + math.sqrt(3) * ib / 2,
                    "current_c_a": -ia / 2 - math.sqrt(3) * ib / 2,
                    "input_power_w": p_in,
                    "load_power_w": p_load,
                    "coupling_loss_w": p_loss,
                    "stored_energy_j": energy,
                    "filtered_p_w": pf,
                    "filtered_q_var": qf,
                }
            )
        start = len(self.config["nodes"]) * self.WIDTH
        lines = []
        for k, (_, _, line) in enumerate(self.lines):
            i, j = y[start + 2 * k : start + 2 * k + 2]
            closed, resistance = self.line_mode(line, t)
            ploss = 1.5 * resistance * (i * i + j * j)
            total_loss += ploss
            lines.append(
                {
                    "tie": line["id"],
                    "a": line["a"],
                    "b": line["b"],
                    "closed": closed,
                    "current_alpha_a": i,
                    "current_beta_a": j,
                    "current_peak_a": math.hypot(i, j),
                    "resistive_loss_w": ploss,
                    "inductor_energy_j": 0.75 * line["l_h"] * (i * i + j * j),
                }
            )
            stored += 0.75 * line["l_h"] * (i * i + j * j)
            stored_rate += (
                1.5
                * line["l_h"]
                * (i * rhs[start + 2 * k] + j * rhs[start + 2 * k + 1])
            )
        return {
            "time_s": t,
            "nodes": records,
            "lines": lines,
            "input_power_w": total_input,
            "load_power_w": total_load,
            "resistive_loss_w": total_loss,
            "stored_energy_j": stored,
            "power_balance_residual_w": total_input
            - total_loss
            - total_load
            - stored_rate,
        }

    def samples(self):
        c = self.config
        y = tuple(self.initial)
        t = 0.0
        output_index = 0
        yield self.diagnostics(t, y)
        while t < c["duration_s"]:
            output_index += 1
            next_output = min(c["duration_s"], output_index * c["output_interval_s"])
            epsilon = max(1e-12, 8 * math.ulp(max(1.0, abs(next_output))))
            stops = [
                event
                for event in self.event_times
                if t + epsilon < event < next_output - epsilon
            ] + [next_output]
            for stop in stops:
                count = max(1, math.ceil((stop - t) / c["step_s"]))
                dt = (stop - t) / count

                def segment_rhs(time, state):
                    near = [
                        event
                        for event in self.event_times
                        if abs(event - stop) <= epsilon
                    ]
                    if near and time >= stop:
                        time = min(near) - 2 * epsilon
                    return self.rhs(time, state)

                for index in range(count):
                    y = rk4_step(segment_rhs, t + index * dt, y, dt)
                t = stop
            yield self.diagnostics(t, y)
