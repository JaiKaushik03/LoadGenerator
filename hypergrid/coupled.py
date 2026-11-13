"""Two-way resource/EMT co-simulation over a declared short electrical window.

Every macro interval bounds the AC source/sink using available DC-side energy,
then integrates actual electrical port energy with RK4 and updates the storage
inventory from that port. The bridge is ideal and lossless; coupling-R and
network losses are physical. No semiconductor/DC/DC losses are invented.
"""

import copy
import math
from .city import CityModel, schedule_value, time_epsilon
from .lcl import network_model
from .energy import finite
from .numerics import rk4_step


class CoupledModel:
    def __init__(self, city_config, electrical_config, resource_interval_s):
        self.city = CityModel(city_config)
        self.electrical = network_model(electrical_config)
        self.interval = finite(
            "resource_interval_s", resource_interval_s, electrical_config["step_s"]
        )
        self.nodes = {n["id"]: n for n in self.city.config["nodes"]}
        if set(self.nodes) != set(self.electrical.index):
            raise ValueError("Every city node must map to exactly one EMT node")
        if self.city.config["ties"]:
            raise ValueError(
                "Coupled mode uses electrical.lines; city.ties must be empty to avoid conflicting network definitions"
            )
        if self.city.telemetry:
            raise ValueError(
                "Measurement-channel simulation is currently mission-mode only"
            )
        if self.city.config["duration_s"] != self.electrical.config["duration_s"]:
            raise ValueError("City and EMT horizons must match in coupled mode")
        self.original_caps = {
            n["id"]: (
                n.get("source_power_limit_w", math.inf),
                n.get("sink_power_limit_w", math.inf),
            )
            for n in self.electrical.config["nodes"]
        }
        self.state = tuple(self.electrical.initial)
        self.t = 0.0
        self.boundaries = sorted(
            {
                p["time_s"]
                for n in self.nodes.values()
                for s in n["sources"]
                for p in s["availability"]
            }
            | {
                p["time_s"]
                for n in self.nodes.values()
                for load in n["loads"]
                for p in load["demand"]
            }
            | {
                p["time_s"]
                for n in self.nodes.values()
                for tank in n.get("thermal", [])
                for key in ["heater_electric_kw", "demand_kw_th"]
                for p in tank[key]
            }
            | set(self.electrical.event_times)
        )

    def solar_power(self, node, t):
        total = 0.0
        for source in node["sources"]:
            availability = schedule_value(source["availability"], t)
            if source["id"] in self.city.solar:
                pv = self.city.solar[source["id"]].operating_point(
                    source.get("reference_irradiance_w_m2", 1000.0) * availability,
                    dust_transmission=source.get("dust_transmission", 1.0),
                )
                raw = min(source["rated_kw"], pv["array_power_kw"])
            else:
                raw = source["rated_kw"] * availability
            total += raw * source["efficiency"]
        return total

    def intervals(self):
        emt = self.electrical
        c = emt.config
        horizon = min(c["duration_s"], self.city.config["duration_s"])
        macro_index = 1
        while self.t < horizon:
            macro_end = macro_index * self.interval
            end = min(horizon, macro_end)
            if abs(end - horizon) <= time_epsilon(horizon):
                end = horizon
            for boundary in self.boundaries:
                if self.t + time_epsilon(self.t) < boundary < end - time_epsilon(end):
                    end = boundary
                    break
            dt = end - self.t
            resources = {}
            for enode in c["nodes"]:
                node = self.nodes[enode["id"]]
                pv = self.solar_power(node, self.t)
                available = charge = 0.0
                for item in node["storage"]:
                    store = self.city.stores[item["id"]]
                    # Preview uses the same resource physics without mutating state.
                    available += copy.deepcopy(store).step(
                        store.discharge_limit_kw, dt
                    )["power_kw"]
                    charge -= copy.deepcopy(store).step(-store.charge_limit_kw, dt)[
                        "power_kw"
                    ]
                caps = self.original_caps[enode["id"]]
                enode["source_power_limit_w"] = min(caps[0], 1000 * (pv + available))
                enode["sink_power_limit_w"] = min(caps[1], 1000 * max(0.0, charge - pv))
                demand = sum(
                    schedule_value(load["demand"], self.t) for load in node["loads"]
                )
                demand += sum(
                    schedule_value(tank["heater_electric_kw"], self.t)
                    for tank in node.get("thermal", [])
                )
                # Nominal demand maps to an actual three-phase resistive load.
                enode["load_r_ohm"] = (
                    3 * enode["voltage_phase_rms_v"] ** 2 / (max(demand, 1e-12) * 1000)
                )
                if c["step_s"] / (enode["load_r_ohm"] * enode["bus_c_f"]) > 0.1:
                    raise ValueError("Resource demand requires a smaller EMT timestep")
                resources[enode["id"]] = {"pv_available_kw": pv, "demand_kw": demand}
            n = len(c["nodes"])
            base = len(self.state)
            # Per-node port/load energy plus total resistive dissipation [J].
            y = self.state + (0.0,) * (2 * n + 1)
            initial = emt.diagnostics(self.t, self.state)

            def rhs(t, state):
                if abs(t - end) <= time_epsilon(end) and any(
                    abs(event - end) <= time_epsilon(end) for event in emt.event_times
                ):
                    t = end - 2 * time_epsilon(end)
                derivative, powers, loss = emt.rhs_and_powers(t, state)
                derivative = list(derivative)
                for j, (input_power, load_power) in enumerate(powers):
                    derivative[base + 2 * j] = input_power
                    derivative[base + 2 * j + 1] = load_power
                derivative[-1] = loss
                return derivative

            count = math.ceil(dt / c["step_s"])
            step = dt / count
            start = self.t
            for k in range(count):
                y = rk4_step(rhs, start + k * step, y, step)
            self.state = tuple(y[:base])
            self.t = end
            if abs(end - macro_end) <= time_epsilon(end):
                macro_index += 1
            final = emt.diagnostics(end, self.state)
            rows = []
            port_j = load_j = 0.0
            for j, enode in enumerate(c["nodes"]):
                node = self.nodes[enode["id"]]
                r = resources[node["id"]]
                energy_j = y[base + 2 * j]
                actual_kw = energy_j / (dt * 1000)
                remaining = actual_kw - r["pv_available_kw"]
                store_rows = []
                storage_power = 0.0
                for item in node["storage"]:
                    result = self.city.stores[item["id"]].step(remaining, dt)
                    remaining -= result["power_kw"]
                    storage_power += result["power_kw"]
                    store_rows.append({"asset": item["id"], **result})
                # Excess PV can be curtailed; a positive residual means the bridge
                # consumed unbacked energy and the run must fail, never fabricate it.
                if remaining > 1e-7:
                    raise RuntimeError("Coupling requested unavailable resource energy")
                pv_used = actual_kw - storage_power
                if pv_used < -1e-7 or pv_used > r["pv_available_kw"] + 1e-7:
                    raise RuntimeError("Invalid PV/storage coupling balance")
                row = {
                    "node": node["id"],
                    "port_energy_j": energy_j,
                    "mean_port_kw": actual_kw,
                    "mean_load_kw": y[base + 2 * j + 1] / (dt * 1000),
                    "pv_used_kw": max(0.0, pv_used),
                    "pv_curtailed_kw": max(0.0, r["pv_available_kw"] - pv_used),
                    "storage_kw": storage_power,
                    "resource_balance_residual_kw": pv_used + storage_power - actual_kw,
                    "storage": store_rows,
                }
                # Allocate actual AC-load energy to priority demands. Tank heating
                # uses only the supplied electrical share, not requested power.
                budget = row["mean_load_kw"]
                load_rows = []
                specs = {tank["id"]: tank for tank in node.get("thermal", [])}
                loads = [
                    (x["priority"], x["id"], "load", schedule_value(x["demand"], start))
                    for x in node["loads"]
                ]
                loads += [
                    (
                        x["priority"],
                        x["id"],
                        "thermal_storage",
                        schedule_value(x["heater_electric_kw"], start),
                    )
                    for x in node.get("thermal", [])
                ]
                for priority, aid, kind, demand in sorted(loads, key=lambda x: x[0]):
                    served = min(demand, max(0.0, budget))
                    budget -= served
                    load = {
                        "asset": aid,
                        "kind": kind,
                        "priority": priority,
                        "demand_kw": demand,
                        "served_kw": served,
                        "unserved_kw": demand - served,
                    }
                    if kind == "thermal_storage":
                        spec = specs[aid]
                        load.update(
                            self.city.thermal[aid].step(
                                served * spec["cop"],
                                schedule_value(spec["demand_kw_th"], start),
                                dt,
                            )
                        )
                        load["heat_pump_ambient_extraction_kw_th"] = served * max(
                            0.0, spec["cop"] - 1
                        )
                        load["heater_conversion_loss_kw"] = served * max(
                            0.0, 1 - spec["cop"]
                        )
                    load_rows.append(load)
                row["loads"] = load_rows
                row["excess_resistive_load_kw"] = max(0.0, budget)
                rows.append(row)
                port_j += energy_j
                load_j += y[base + 2 * j + 1]
            delta = final["stored_energy_j"] - initial["stored_energy_j"]
            residual = port_j - load_j - y[-1] - delta
            yield {
                "start_s": start,
                "end_s": end,
                "dt_s": dt,
                "nodes": rows,
                "electrical": final,
                "port_energy_j": port_j,
                "load_energy_j": load_j,
                "network_loss_j": y[-1],
                "electrical_stored_change_j": delta,
                "electrical_balance_residual_j": residual,
            }
