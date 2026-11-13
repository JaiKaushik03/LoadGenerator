"""City-scale energy accounting, not an AC load-flow or switched circuit solver.

All powers are bus-side kW. Steps represent intervals; state is recorded at
their ends. Direct interties use configured fractional transmission losses.
Dispatch is deterministic local-first, followed by ordered direct exchanges.
"""

import copy
import math
from .energy import Storage, battery_capacity_kwh, finite
from .thermal import ThermalTank
from .reactants import RegenerativeFuelCell, OXYGEN_PER_HYDROGEN, WATER_PER_HYDROGEN
from .solar import SolarArray
from .telemetry import TelemetryChannel


def check_keys(obj, allowed, label):
    if not isinstance(obj, dict):
        raise ValueError(f"{label} must be an object")
    extra = set(obj) - set(allowed.split())
    if extra:
        raise ValueError(f"{label}: unsupported fields {sorted(extra)}")


def schedule_value(schedule, time_s):
    value = schedule[0]["value"]
    for item in schedule:
        if item["time_s"] > time_s + time_epsilon(time_s):
            break
        value = item["value"]
    return value


def time_epsilon(time_s):
    return max(1e-12, 8 * math.ulp(max(1.0, abs(time_s))))


def check_schedule(items, name):
    if not items or items[0]["time_s"] != 0:
        raise ValueError(f"{name}: schedule must start at zero")
    previous = -1
    for item in items:
        check_keys(item, "time_s value", name)
        finite(name, item["time_s"])
        finite(name, item["value"])
        if item["time_s"] <= previous:
            raise ValueError(f"{name}: timestamps must increase")
        previous = item["time_s"]


def default_city():
    names = [
        "power_hub",
        "habitat",
        "isru",
        "science",
        "mobility",
        "communications",
        "emergency",
    ]
    nodes = []
    for i, name in enumerate(names):
        nodes.append(
            {
                "id": f"mg{i}",
                "name": name,
                "sources": [
                    {
                        "id": f"solar{i}",
                        "rated_kw": 150 if i == 0 else 40,
                        "efficiency": 0.97,
                        "availability": [
                            {"time_s": 0, "value": 1},
                            {"time_s": 43200, "value": 0},
                        ],
                    }
                ],
                "loads": [
                    {
                        "id": f"critical{i}",
                        "priority": 0,
                        "demand": [{"time_s": 0, "value": 10}],
                    },
                    {
                        "id": f"flexible{i}",
                        "priority": 1,
                        "demand": [{"time_s": 0, "value": 20}],
                    },
                ],
                "storage": [
                    {
                        "id": f"battery{i}",
                        "kind": "battery",
                        "series_cells": 38,
                        "parallel_cells": 2,
                        "cell_voltage_v": 3.2,
                        "cell_capacity_ah": 314,
                        "initial_fraction": 0.8,
                        "charge_limit_kw": 30,
                        "discharge_limit_kw": 30,
                        "charge_efficiency": 0.95,
                        "discharge_efficiency": 0.95,
                        "min_fraction": 0.1,
                        "max_fraction": 0.95,
                        "self_discharge_per_hour": 0.0001,
                    }
                ],
            }
        )
    return {
        "schema_version": 1,
        "fidelity": "energy_balance",
        "parameter_provenance": "illustrative editable assumptions; not calibrated",
        "duration_s": 86400,
        "step_s": 60,
        "nodes": nodes,
        "ties": [
            {
                "id": f"tie{i}",
                "a": "mg0",
                "b": f"mg{i}",
                "capacity_kw": 50,
                "loss_fraction": 0.02,
                "availability": [{"time_s": 0, "value": 1}],
            }
            for i in range(1, 7)
        ],
    }


def make_storage(item):
    kind = item["kind"]
    if kind == "battery":
        capacity = battery_capacity_kwh(
            item["series_cells"],
            item["parallel_cells"],
            item["cell_voltage_v"],
            item["cell_capacity_ah"],
        )
    elif kind == "supercapacitor":
        c = finite("capacitance_f", item["capacitance_f"], 1e-12)
        vmax = finite("maximum_voltage_v", item["maximum_voltage_v"], 1e-12)
        capacity = 0.5 * c * vmax**2 / 3_600_000
    elif kind == "flywheel":
        j = finite("inertia_kg_m2", item["inertia_kg_m2"], 1e-12)
        wmax = finite("maximum_speed_rad_s", item["maximum_speed_rad_s"], 1e-12)
        capacity = 0.5 * j * wmax**2 / 3_600_000
    elif kind == "regenerative_fuel_cell":
        # Inventory-equivalent chemical energy; not pressure/reactant dynamics.
        capacity = finite(
            "hydrogen_capacity_kg", item["hydrogen_capacity_kg"], 1e-12
        ) * finite(
            "hydrogen_specific_energy_kwh_kg",
            item["hydrogen_specific_energy_kwh_kg"],
            1e-12,
        )
    else:
        raise ValueError(
            f"Unsupported electrical storage kind {kind}; thermal storage requires a separate heat domain"
        )
    fraction = finite("initial_fraction", item["initial_fraction"], 0, 1)
    args = (
        item["id"],
        capacity,
        capacity * fraction,
        item["charge_limit_kw"],
        item["discharge_limit_kw"],
        item["charge_efficiency"],
        item["discharge_efficiency"],
        item["min_fraction"],
        item["max_fraction"],
        item["self_discharge_per_hour"],
    )
    if kind == "regenerative_fuel_cell":
        mass = item["hydrogen_capacity_kg"]
        return RegenerativeFuelCell(
            *args,
            specific_energy_kwh_kg=item["hydrogen_specific_energy_kwh_kg"],
            oxygen_kg=item.get(
                "initial_oxygen_kg", mass * fraction * OXYGEN_PER_HYDROGEN
            ),
            water_kg=item.get(
                "initial_water_kg", mass * (1 - fraction) * WATER_PER_HYDROGEN
            ),
        )
    return Storage(*args)


class CityModel:
    def __init__(self, config):
        self.config = copy.deepcopy(config)
        c = self.config
        check_keys(
            c,
            "schema_version fidelity parameter_provenance duration_s step_s output_interval_s nodes ties telemetry",
            "config",
        )
        if c.get("schema_version") != 1 or c.get("fidelity") != "energy_balance":
            raise ValueError("Requires schema_version=1, fidelity=energy_balance")
        if (
            not isinstance(c.get("parameter_provenance"), str)
            or len(c["parameter_provenance"]) > 4096
        ):
            raise ValueError(
                "Parameter provenance must be text of at most 4096 characters"
            )
        finite("duration_s", c["duration_s"], 1e-9)
        finite("step_s", c["step_s"], 1e-9)
        finite(
            "output_interval_s", c.get("output_interval_s", c["step_s"]), c["step_s"]
        )
        if c["duration_s"] / c["step_s"] > 10_000_000:
            raise ValueError(
                "More than 10 million steps; choose a coarser step or split the run"
            )
        self.stores = {}
        self.elapsed_s = 0.0
        self.thermal = {}
        self.solar = {}
        ids = set()
        for node in c["nodes"]:
            check_keys(node, "id name sources loads storage thermal", "node")
            if not isinstance(node["id"], str) or not 1 <= len(node["id"]) <= 128:
                raise ValueError("Node ID must be a nonempty string")
        node_ids = {n["id"] for n in c["nodes"]}
        if not node_ids or len(node_ids) != len(c["nodes"]):
            raise ValueError("Nodes must have unique IDs and cannot be empty")
        for node in c["nodes"]:
            for group in ["sources", "loads", "storage", "thermal"]:
                for item in node.get(group, []):
                    if (
                        not isinstance(item["id"], str)
                        or not item["id"]
                        or len(item["id"]) > 128
                        or item["id"] in ids
                    ):
                        raise ValueError(
                            "Asset IDs must be nonempty globally unique strings"
                        )
                    ids.add(item["id"])
            for s in node["sources"]:
                check_keys(
                    s,
                    "id rated_kw efficiency availability pv dust_transmission reference_irradiance_w_m2",
                    "source",
                )
                finite("rated_kw", s["rated_kw"])
                finite("efficiency", s["efficiency"], 1e-12, 1)
                check_schedule(s["availability"], s["id"])
                if any(p["value"] > 1 for p in s["availability"]):
                    raise ValueError("Source availability must be in [0,1]")
                if "pv" in s:
                    if not isinstance(s["pv"], dict):
                        raise ValueError("pv must contain cell-equivalent parameters")
                    self.solar[s["id"]] = SolarArray(**s["pv"])
                    finite(
                        "dust_transmission", s.get("dust_transmission", 1.0), 0.0, 1.0
                    )
                    finite(
                        "reference_irradiance_w_m2",
                        s.get("reference_irradiance_w_m2", 1000.0),
                        0.0,
                        5000.0,
                    )
                elif "dust_transmission" in s or "reference_irradiance_w_m2" in s:
                    raise ValueError(
                        "Irradiance/dust settings require a pv source model"
                    )
            for load in node["loads"]:
                check_keys(load, "id priority demand", "load")
                finite("priority", load["priority"])
                check_schedule(load["demand"], load["id"])
            for s in node["storage"]:
                shared = "id kind initial_fraction charge_limit_kw discharge_limit_kw charge_efficiency discharge_efficiency min_fraction max_fraction self_discharge_per_hour "
                specific = {
                    "battery": "series_cells parallel_cells cell_voltage_v cell_capacity_ah",
                    "supercapacitor": "capacitance_f maximum_voltage_v",
                    "flywheel": "inertia_kg_m2 maximum_speed_rad_s",
                    "regenerative_fuel_cell": "hydrogen_capacity_kg hydrogen_specific_energy_kwh_kg initial_oxygen_kg initial_water_kg",
                }
                if s["kind"] not in specific:
                    raise ValueError(
                        "Unsupported storage kind; do not mix heat and electric energy"
                    )
                check_keys(s, shared + specific[s["kind"]], "storage")
                self.stores[s["id"]] = make_storage(s)
            for tank in node.get("thermal", []):
                check_keys(
                    tank,
                    "id mass_kg specific_heat_j_kg_k initial_temperature_c ambient_c conductance_w_k min_temperature_c max_temperature_c heater_electric_kw demand_kw_th cop priority",
                    "thermal",
                )
                finite("cop", tank["cop"], 1e-12)
                finite("priority", tank["priority"])
                check_schedule(tank["heater_electric_kw"], tank["id"])
                check_schedule(tank["demand_kw_th"], tank["id"])
                self.thermal[tank["id"]] = ThermalTank(
                    tank["mass_kg"],
                    tank["specific_heat_j_kg_k"],
                    tank["initial_temperature_c"],
                    tank["ambient_c"],
                    tank["conductance_w_k"],
                    tank["min_temperature_c"],
                    tank["max_temperature_c"],
                )
        self.telemetry = TelemetryChannel(c["telemetry"]) if "telemetry" in c else None
        if self.telemetry:
            for attack in c["telemetry"]["attacks"]:
                if not set(attack["targets"]) <= ids:
                    raise ValueError("Unknown telemetry attack target")
        tie_ids = set()
        for tie in c["ties"]:
            check_keys(tie, "id a b capacity_kw loss_fraction availability", "tie")
            if (
                tie["id"] in tie_ids
                or tie["a"] == tie["b"]
                or not {tie["a"], tie["b"]} <= node_ids
            ):
                raise ValueError("Invalid tie endpoints or duplicate ID")
            tie_ids.add(tie["id"])
            finite("capacity_kw", tie["capacity_kw"])
            finite("loss_fraction", tie["loss_fraction"], 0, 0.999999)
            check_schedule(tie["availability"], tie["id"])
            if any(p["value"] > 1 for p in tie["availability"]):
                raise ValueError("Tie availability must be in [0,1]")

    def intervals(self):
        """Yield bounded-memory records; integrate exactly across schedule changes."""
        c = self.config
        transitions = {
            p["time_s"]
            for n in c["nodes"]
            for s in n["sources"]
            for p in s["availability"]
        }
        transitions |= {
            p["time_s"] for n in c["nodes"] for s in n["loads"] for p in s["demand"]
        }
        transitions |= {p["time_s"] for tie in c["ties"] for p in tie["availability"]}
        transitions |= {
            p["time_s"]
            for n in c["nodes"]
            for tank in n.get("thermal", [])
            for key in ["heater_electric_kw", "demand_kw_th"]
            for p in tank[key]
        }
        if self.telemetry:
            transitions |= {
                a[key]
                for a in c["telemetry"]["attacks"]
                for key in ["start_s", "end_s"]
            }
        boundaries = sorted(t for t in transitions if 0 < t < c["duration_s"])
        t = self.elapsed_s
        boundary = 0
        output_interval = c.get("output_interval_s", c["step_s"])
        step_index = math.floor((t + time_epsilon(t)) / c["step_s"]) + 1
        output_index = math.floor((t + time_epsilon(t)) / output_interval) + 1
        while t < c["duration_s"]:
            while boundary < len(boundaries) and boundaries[
                boundary
            ] <= t + time_epsilon(t):
                boundary += 1
            step_end = step_index * c["step_s"]
            output_end = output_index * output_interval
            end = min(step_end, output_end, c["duration_s"])
            if boundary < len(boundaries):
                end = min(end, boundaries[boundary])
            if abs(end - output_end) <= time_epsilon(end):
                end = min(output_end, c["duration_s"])
            dt = end - t
            h = dt / 3600
            nodes, assets, balances = {}, [], {}
            for node in c["nodes"]:
                nid = node["id"]
                source_kw = 0.0
                for source in node["sources"]:
                    raw = source["rated_kw"] * schedule_value(source["availability"], t)
                    solar_state = {}
                    if source["id"] in self.solar:
                        solar_state = dict(
                            self.solar[source["id"]].operating_point(
                                source.get("reference_irradiance_w_m2", 1000.0)
                                * schedule_value(source["availability"], t),
                                dust_transmission=source.get("dust_transmission", 1.0),
                            )
                        )
                        raw = min(source["rated_kw"], solar_state["array_power_kw"])
                        solar_state["mppt_clipping_kw"] = (
                            solar_state["array_power_kw"] - raw
                        )
                    p = raw * source["efficiency"]
                    source_kw += p
                    assets.append(
                        {
                            "node": nid,
                            "asset": source["id"],
                            "kind": "source",
                            "power_kw": p,
                            "conversion_loss_kw": raw - p,
                            **solar_state,
                        }
                    )
                demand = sum(
                    schedule_value(load["demand"], t) for load in node["loads"]
                )
                demand += sum(
                    schedule_value(tank["heater_electric_kw"], t)
                    for tank in node.get("thermal", [])
                )
                surplus = source_kw - demand
                storage_kw = storage_loss_kwh = storage_residual_kwh = 0.0
                for item in node["storage"]:
                    result = self.stores[item["id"]].step(-surplus, dt)
                    if item["kind"] == "supercapacitor":
                        result["internal_voltage_v"] = math.sqrt(
                            2 * result["energy_kwh"] * 3_600_000 / item["capacitance_f"]
                        )
                    elif item["kind"] == "flywheel":
                        result["speed_rad_s"] = math.sqrt(
                            2 * result["energy_kwh"] * 3_600_000 / item["inertia_kg_m2"]
                        )
                    elif item["kind"] == "battery":
                        cells = item["series_cells"] * item["parallel_cells"]
                        result.update(
                            cell_count=cells,
                            series_cells=item["series_cells"],
                            parallel_strings=item["parallel_cells"],
                            mean_cell_energy_wh=result["energy_kwh"] * 1000 / cells,
                            mean_cell_terminal_power_w=result["power_kw"]
                            * 1000
                            / cells,
                            cell_state_basis="uniform aggregate equivalent; not independent cell trajectories",
                        )
                    storage_kw += result["power_kw"]
                    storage_loss_kwh += result["loss_kwh"]
                    storage_residual_kwh += result["balance_residual_kwh"]
                    surplus += result["power_kw"]
                    assets.append(
                        {
                            "node": nid,
                            "asset": item["id"],
                            "kind": item["kind"],
                            **result,
                        }
                    )
                balances[nid] = surplus
                nodes[nid] = {
                    "node": nid,
                    "generation_kw": source_kw,
                    "demand_kw": demand,
                    "storage_kw": storage_kw,
                    "storage_loss_kwh": storage_loss_kwh,
                    "storage_balance_residual_kwh": storage_residual_kwh,
                    "import_kw": 0.0,
                    "export_kw": 0.0,
                }
            ties = []
            for tie in c["ties"]:
                a, b = tie["a"], tie["b"]
                if balances[a] < 0 < balances[b]:
                    a, b = b, a
                eff = 1 - tie["loss_fraction"]
                sent = min(
                    max(0, balances[a]),
                    max(0, -balances[b]) / eff,
                    tie["capacity_kw"] * schedule_value(tie["availability"], t),
                )
                received = sent * eff
                balances[a] -= sent
                balances[b] += received
                nodes[a]["export_kw"] += sent
                nodes[b]["import_kw"] += received
                ties.append(
                    {
                        "tie": tie["id"],
                        "from": a,
                        "to": b,
                        "sent_kw": sent,
                        "received_kw": received,
                        "loss_kw": sent - received,
                    }
                )
            for node in c["nodes"]:
                nid = node["id"]
                unmet = max(0, -balances[nid])
                record = nodes[nid]
                record.update(
                    unserved_kw=unmet,
                    curtailed_kw=max(0, balances[nid]),
                    served_kw=record["demand_kw"] - unmet,
                )
                record["actual_generation_kw"] = (
                    record["generation_kw"] - record["curtailed_kw"]
                )
                for source in (
                    a for a in assets if a["node"] == nid and a["kind"] == "source"
                ):
                    share = (
                        source["power_kw"] / record["generation_kw"]
                        if record["generation_kw"]
                        else 0.0
                    )
                    source["curtailed_kw"] = record["curtailed_kw"] * share
                    source["actual_power_kw"] = (
                        source["power_kw"] - source["curtailed_kw"]
                    )
                budget = record["served_kw"]
                loads = [
                    (
                        load["priority"],
                        load["id"],
                        "load",
                        schedule_value(load["demand"], t),
                    )
                    for load in node["loads"]
                ]
                loads += [
                    (
                        tank["priority"],
                        tank["id"],
                        "thermal_storage",
                        schedule_value(tank["heater_electric_kw"], t),
                    )
                    for tank in node.get("thermal", [])
                ]
                tank_specs = {tank["id"]: tank for tank in node.get("thermal", [])}
                for priority, asset_id, kind, demand in sorted(
                    loads, key=lambda x: x[0]
                ):
                    served = min(demand, max(0, budget))
                    budget -= served
                    asset = {
                        "node": nid,
                        "asset": asset_id,
                        "kind": kind,
                        "priority": priority,
                        "demand_kw": demand,
                        "served_kw": served,
                        "unserved_kw": demand - served,
                    }
                    if kind == "thermal_storage":
                        spec = tank_specs[asset_id]
                        asset.update(
                            self.thermal[asset_id].step(
                                served * spec["cop"],
                                schedule_value(spec["demand_kw_th"], t),
                                dt,
                            )
                        )
                        asset["heater_conversion_loss_kw"] = served * max(
                            0.0, 1 - spec["cop"]
                        )
                        asset["heat_pump_ambient_extraction_kw_th"] = served * max(
                            0.0, spec["cop"] - 1
                        )
                    assets.append(asset)
            city = {
                key: sum(n[key] for n in nodes.values())
                for key in [
                    "generation_kw",
                    "demand_kw",
                    "storage_kw",
                    "served_kw",
                    "unserved_kw",
                    "curtailed_kw",
                    "storage_loss_kwh",
                    "storage_balance_residual_kwh",
                ]
            }
            city["transmission_loss_kw"] = sum(tie["loss_kw"] for tie in ties)
            city["actual_generation_kw"] = sum(
                n["actual_generation_kw"] for n in nodes.values()
            )
            city["unserved_kwh"] = city["unserved_kw"] * h
            city["balance_residual_kw"] = (
                city["generation_kw"]
                + city["storage_kw"]
                - city["served_kw"]
                - city["curtailed_kw"]
                - city["transmission_loss_kw"]
            )
            for key in [
                "input_kw_th",
                "served_kw_th",
                "unserved_kw_th",
                "dump_kw_th",
                "ambient_loss_kwh_th",
                "stored_change_kwh_th",
                "balance_residual_kwh_th",
            ]:
                city[key] = sum(
                    a.get(key, 0.0) for a in assets if a["kind"] == "thermal_storage"
                )
            if self.telemetry:
                truth = {
                    a["asset"]: a.get(
                        "actual_power_kw", a.get("power_kw", a.get("served_kw", 0.0))
                    )
                    for a in assets
                }
                observations = self.telemetry.sample(end, truth)
                for asset in assets:
                    asset.update(observations[asset["asset"]])
            self.elapsed_s = end
            yield {
                "start_s": t,
                "end_s": end,
                "dt_s": dt,
                "city": city,
                "nodes": list(nodes.values()),
                "assets": assets,
                "ties": ties,
            }
            t = end
            if abs(t - step_end) <= time_epsilon(t):
                step_index += 1
            if abs(t - output_end) <= time_epsilon(t):
                output_index += 1
            if boundary < len(boundaries) and t == boundaries[boundary]:
                boundary += 1

    def outputs(self):
        """Aggregate interval energies and mean powers; retain end states.

        Telemetry and state variables describe the final integration interval.
        No samples are silently discarded and stored energy is never summed.
        """
        interval = self.config.get("output_interval_s", self.config["step_s"])
        index = (
            math.floor((self.elapsed_s + time_epsilon(self.elapsed_s)) / interval) + 1
        )
        accumulator = None
        delta_keys = {
            "loss_kwh",
            "storage_loss_kwh",
            "unserved_kwh",
            "stored_change_kwh_th",
            "ambient_loss_kwh_th",
            "balance_residual_kwh",
            "storage_balance_residual_kwh",
            "balance_residual_kwh_th",
            "leaked_hydrogen_kg",
            "mass_balance_residual_kg",
        }

        def merge(previous, current, old_dt, new_dt):
            result = dict(current)
            for key, value in current.items():
                old = previous.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not isinstance(old, (int, float))
                ):
                    continue
                if key in delta_keys:
                    result[key] = old + value
                elif (
                    key.endswith("_kw")
                    or key.endswith("_kw_th")
                    or key.endswith("_power_w")
                ) and key not in [
                    "observed_power_kw",
                    "ground_truth_power_kw",
                ]:
                    result[key] = (old * old_dt + value * new_dt) / (old_dt + new_dt)
            return result

        for row in self.intervals():
            if accumulator is None:
                accumulator = copy.deepcopy(row)
                accumulator["integration_intervals"] = 1
            else:
                old_dt = accumulator["dt_s"]
                new_dt = row["dt_s"]
                accumulator["city"] = merge(
                    accumulator["city"], row["city"], old_dt, new_dt
                )
                for group, key in [
                    ("nodes", "node"),
                    ("assets", "asset"),
                    ("ties", "tie"),
                ]:
                    previous = {r[key]: r for r in accumulator[group]}
                    accumulator[group] = [
                        merge(previous[r[key]], r, old_dt, new_dt) for r in row[group]
                    ]
                accumulator["end_s"] = row["end_s"]
                accumulator["dt_s"] += new_dt
                accumulator["integration_intervals"] += 1
            boundary = min(self.config["duration_s"], index * interval)
            if abs(row["end_s"] - boundary) <= time_epsilon(boundary):
                yield accumulator
                accumulator = None
                index += 1
        if accumulator is not None:
            raise RuntimeError("Unflushed mission output interval")

    def snapshot(self):
        stores = {}
        for aid, store in self.stores.items():
            stores[aid] = {"energy_kwh": store.energy_kwh}
            if isinstance(store, RegenerativeFuelCell):
                stores[aid].update(oxygen_kg=store.oxygen_kg, water_kg=store.water_kg)
        return {
            "schema_version": 1,
            "elapsed_s": self.elapsed_s,
            "stores": stores,
            "thermal": {aid: tank.temperature_c for aid, tank in self.thermal.items()},
            "telemetry": self.telemetry.snapshot() if self.telemetry else None,
        }

    def restore(self, state):
        candidate = copy.deepcopy(self)
        candidate._restore_checked(state)
        self.__dict__.clear()
        self.__dict__.update(candidate.__dict__)

    def _restore_checked(self, state):
        if (
            set(state)
            != {"schema_version", "elapsed_s", "stores", "thermal", "telemetry"}
            or state["schema_version"] != 1
        ):
            raise ValueError("Unsupported model checkpoint")
        finite("elapsed_s", state["elapsed_s"], 0.0, self.config["duration_s"])
        out = self.config.get("output_interval_s", self.config["step_s"])
        elapsed = state["elapsed_s"]
        if elapsed != self.config["duration_s"] and abs(
            elapsed - round(elapsed / out) * out
        ) > time_epsilon(elapsed):
            raise ValueError("Checkpoint must be at an output boundary")
        if set(state["stores"]) != set(self.stores) or set(state["thermal"]) != set(
            self.thermal
        ):
            raise ValueError("Checkpoint asset mismatch")
        for aid, values in state["stores"].items():
            store = self.stores[aid]
            expected = (
                {"energy_kwh", "oxygen_kg", "water_kg"}
                if isinstance(store, RegenerativeFuelCell)
                else {"energy_kwh"}
            )
            if set(values) != expected:
                raise ValueError("Invalid storage checkpoint fields")
            finite(
                "energy_kwh",
                values["energy_kwh"],
                0.0,
                store.capacity_kwh * (1 + 1e-12),
            )
            for key in expected - {"energy_kwh"}:
                finite(key, values[key])
            for key, value in values.items():
                setattr(store, key, value)
        for aid, temperature in state["thermal"].items():
            finite("temperature_c", temperature, -273.15)
            self.thermal[aid].temperature_c = temperature
        if bool(self.telemetry) != (state["telemetry"] is not None):
            raise ValueError("Telemetry checkpoint mismatch")
        if self.telemetry:
            ids = {
                a["id"]
                for n in self.config["nodes"]
                for g in ["sources", "loads", "storage", "thermal"]
                for a in n.get(g, [])
            }
            self.telemetry.restore(state["telemetry"], ids, elapsed)
        self.elapsed_s = elapsed
