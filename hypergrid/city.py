"""City-scale energy accounting, not an AC load-flow or switched circuit solver.

All powers are bus-side kW. Steps represent intervals; state is recorded at
their ends. Direct interties use configured fractional transmission losses.
Dispatch is deterministic local-first, followed by ordered direct exchanges.
"""
import copy
import math
from .energy import Storage, battery_capacity_kwh, finite


def check_keys(obj, allowed, label):
    if not isinstance(obj, dict):
        raise ValueError(f'{label} must be an object')
    extra = set(obj) - set(allowed.split())
    if extra:
        raise ValueError(f'{label}: unsupported fields {sorted(extra)}')


def schedule_value(schedule, time_s):
    value = schedule[0]["value"]
    for item in schedule:
        if item["time_s"] > time_s:
            break
        value = item["value"]
    return value


def check_schedule(items, name):
    if not items or items[0]["time_s"] != 0:
        raise ValueError(f"{name}: schedule must start at zero")
    previous = -1
    for item in items:
        check_keys(item, 'time_s value', name)
        finite(name, item["time_s"])
        finite(name, item["value"])
        if item["time_s"] <= previous:
            raise ValueError(f"{name}: timestamps must increase")
        previous = item["time_s"]


def default_city():
    names = ["power_hub", "habitat", "isru", "science", "mobility", "communications", "emergency"]
    nodes = []
    for i, name in enumerate(names):
        nodes.append({
            "id": f"mg{i}", "name": name,
            "sources": [{"id": f"solar{i}", "rated_kw": 150 if i == 0 else 40,
                         "efficiency": 0.97,
                         "availability": [{"time_s": 0, "value": 1},
                                          {"time_s": 43200, "value": 0}]}],
            "loads": [{"id": f"critical{i}", "priority": 0,
                       "demand": [{"time_s": 0, "value": 10}]},
                      {"id": f"flexible{i}", "priority": 1,
                       "demand": [{"time_s": 0, "value": 20}]}],
            "storage": [{"id": f"battery{i}", "kind": "battery",
                         "series_cells": 38, "parallel_cells": 2,
                         "cell_voltage_v": 3.2, "cell_capacity_ah": 314,
                         "initial_fraction": 0.8, "charge_limit_kw": 30,
                         "discharge_limit_kw": 30,
                         "charge_efficiency": 0.95, "discharge_efficiency": 0.95,
                         "min_fraction": 0.1, "max_fraction": 0.95,
                         "self_discharge_per_hour": 0.0001}]
        })
    return {"schema_version": 1, "fidelity": "energy_balance",
            "parameter_provenance": "illustrative editable assumptions; not calibrated",
            "duration_s": 86400, "step_s": 60,
            "nodes": nodes,
            "ties": [{"id": f"tie{i}", "a": "mg0", "b": f"mg{i}",
                      "capacity_kw": 50, "loss_fraction": 0.02,
                      "availability": [{"time_s": 0, "value": 1}]} for i in range(1, 7)]}


def make_storage(item):
    kind = item["kind"]
    if kind == "battery":
        capacity = battery_capacity_kwh(item["series_cells"], item["parallel_cells"],
                                        item["cell_voltage_v"], item["cell_capacity_ah"])
    elif kind == "supercapacitor":
        c = finite("capacitance_f", item["capacitance_f"], 1e-12)
        vmax = finite("maximum_voltage_v", item["maximum_voltage_v"], 1e-12)
        capacity = 0.5 * c * vmax ** 2 / 3_600_000
    elif kind == "flywheel":
        j = finite("inertia_kg_m2", item["inertia_kg_m2"], 1e-12)
        wmax = finite("maximum_speed_rad_s", item["maximum_speed_rad_s"], 1e-12)
        capacity = 0.5 * j * wmax ** 2 / 3_600_000
    elif kind == "regenerative_fuel_cell":
        # Inventory-equivalent chemical energy; not pressure/reactant dynamics.
        capacity = finite("hydrogen_capacity_kg", item["hydrogen_capacity_kg"], 1e-12) * finite(
            "hydrogen_specific_energy_kwh_kg", item["hydrogen_specific_energy_kwh_kg"], 1e-12)
    else:
        raise ValueError(f"Unsupported electrical storage kind {kind}; thermal storage requires a separate heat domain")
    fraction = finite("initial_fraction", item["initial_fraction"], 0, 1)
    return Storage(item["id"], capacity, capacity * fraction,
                   item["charge_limit_kw"], item["discharge_limit_kw"],
                   item["charge_efficiency"], item["discharge_efficiency"],
                   item["min_fraction"], item["max_fraction"], item["self_discharge_per_hour"])


class CityModel:
    def __init__(self, config):
        self.config = copy.deepcopy(config)
        c = self.config
        check_keys(c, 'schema_version fidelity parameter_provenance duration_s step_s nodes ties', 'config')
        if c.get("schema_version") != 1 or c.get("fidelity") != "energy_balance":
            raise ValueError("Requires schema_version=1, fidelity=energy_balance")
        finite("duration_s", c["duration_s"], 1e-9)
        finite("step_s", c["step_s"], 1e-9)
        if c["duration_s"] / c["step_s"] > 10_000_000:
            raise ValueError("More than 10 million steps; choose a coarser step or split the run")
        self.stores = {}
        ids = set()
        for node in c['nodes']:
            check_keys(node, 'id name sources loads storage', 'node')
            if not isinstance(node['id'], str) or not node['id']:
                raise ValueError('Node ID must be a nonempty string')
        node_ids = {n["id"] for n in c["nodes"]}
        if not node_ids or len(node_ids) != len(c["nodes"]):
            raise ValueError("Nodes must have unique IDs and cannot be empty")
        for node in c["nodes"]:
            for group in ["sources", "loads", "storage"]:
                for item in node[group]:
                    if not isinstance(item["id"], str) or not item["id"] or item["id"] in ids:
                        raise ValueError("Asset IDs must be nonempty globally unique strings")
                    ids.add(item["id"])
            for s in node["sources"]:
                check_keys(s, 'id rated_kw efficiency availability', 'source')
                finite("rated_kw", s["rated_kw"])
                finite("efficiency", s["efficiency"], 1e-12, 1)
                check_schedule(s["availability"], s["id"])
                if any(p["value"] > 1 for p in s["availability"]):
                    raise ValueError("Source availability must be in [0,1]")
            for load in node["loads"]:
                check_keys(load, 'id priority demand', 'load')
                finite("priority", load["priority"])
                check_schedule(load["demand"], load["id"])
            for s in node["storage"]:
                shared = 'id kind initial_fraction charge_limit_kw discharge_limit_kw charge_efficiency discharge_efficiency min_fraction max_fraction self_discharge_per_hour '
                specific = {'battery': 'series_cells parallel_cells cell_voltage_v cell_capacity_ah',
                            'supercapacitor': 'capacitance_f maximum_voltage_v',
                            'flywheel': 'inertia_kg_m2 maximum_speed_rad_s',
                            'regenerative_fuel_cell': 'hydrogen_capacity_kg hydrogen_specific_energy_kwh_kg'}
                if s['kind'] not in specific:
                    raise ValueError('Unsupported storage kind; do not mix heat and electric energy')
                check_keys(s, shared + specific[s['kind']], 'storage')
                self.stores[s["id"]] = make_storage(s)
        tie_ids = set()
        for tie in c["ties"]:
            check_keys(tie, 'id a b capacity_kw loss_fraction availability', 'tie')
            if tie["id"] in tie_ids or tie["a"] == tie["b"] or not {tie["a"], tie["b"]} <= node_ids:
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
        transitions = {p["time_s"] for n in c["nodes"] for s in n["sources"] for p in s["availability"]}
        transitions |= {p["time_s"] for n in c["nodes"] for s in n["loads"] for p in s["demand"]}
        transitions |= {p["time_s"] for tie in c["ties"] for p in tie["availability"]}
        boundaries = sorted(t for t in transitions if 0 < t < c["duration_s"])
        t = 0.0
        boundary = 0
        while t < c["duration_s"]:
            end = min(t + c["step_s"], c["duration_s"])
            if boundary < len(boundaries):
                end = min(end, boundaries[boundary])
            dt = end - t
            h = dt / 3600
            nodes, assets, balances = {}, [], {}
            for node in c["nodes"]:
                nid = node["id"]
                source_kw = 0.0
                for source in node["sources"]:
                    raw = source["rated_kw"] * schedule_value(source["availability"], t)
                    p = raw * source["efficiency"]
                    source_kw += p
                    assets.append({"node": nid, "asset": source["id"], "kind": "source",
                                   "power_kw": p, "conversion_loss_kw": raw - p})
                demand = sum(schedule_value(load["demand"], t) for load in node["loads"])
                surplus = source_kw - demand
                storage_kw = storage_loss_kwh = storage_residual_kwh = 0.0
                for item in node["storage"]:
                    result = self.stores[item["id"]].step(-surplus, dt)
                    storage_kw += result["power_kw"]
                    storage_loss_kwh += result["loss_kwh"]
                    storage_residual_kwh += result["balance_residual_kwh"]
                    surplus += result["power_kw"]
                    assets.append({"node": nid, "asset": item["id"], "kind": item["kind"], **result})
                balances[nid] = surplus
                nodes[nid] = {"node": nid, "generation_kw": source_kw, "demand_kw": demand,
                              "storage_kw": storage_kw, "storage_loss_kwh": storage_loss_kwh,
                              "storage_balance_residual_kwh": storage_residual_kwh,
                              "import_kw": 0.0, "export_kw": 0.0}
            ties = []
            for tie in c["ties"]:
                a, b = tie["a"], tie["b"]
                if balances[a] < 0 < balances[b]:
                    a, b = b, a
                eff = 1 - tie["loss_fraction"]
                sent = min(max(0, balances[a]), max(0, -balances[b]) / eff,
                           tie["capacity_kw"] * schedule_value(tie["availability"], t))
                received = sent * eff
                balances[a] -= sent
                balances[b] += received
                nodes[a]["export_kw"] += sent
                nodes[b]["import_kw"] += received
                ties.append({"tie": tie["id"], "from": a, "to": b,
                             "sent_kw": sent, "received_kw": received, "loss_kw": sent - received})
            for node in c["nodes"]:
                nid = node["id"]
                unmet = max(0, -balances[nid])
                record = nodes[nid]
                record.update(unserved_kw=unmet, curtailed_kw=max(0, balances[nid]),
                              served_kw=record["demand_kw"] - unmet)
                budget = record["served_kw"]
                for load in sorted(node["loads"], key=lambda x: x["priority"]):
                    demand = schedule_value(load["demand"], t)
                    served = min(demand, max(0, budget))
                    budget -= served
                    assets.append({"node": nid, "asset": load["id"], "kind": "load",
                                   "priority": load["priority"], "demand_kw": demand,
                                   "served_kw": served, "unserved_kw": demand - served})
            city = {key: sum(n[key] for n in nodes.values()) for key in
                    ["generation_kw", "demand_kw", "storage_kw", "served_kw", "unserved_kw",
                     "curtailed_kw", "storage_loss_kwh", "storage_balance_residual_kwh"]}
            city["transmission_loss_kw"] = sum(tie["loss_kw"] for tie in ties)
            city["unserved_kwh"] = city["unserved_kw"] * h
            city["balance_residual_kw"] = (city["generation_kw"] + city["storage_kw"]
                - city["served_kw"] - city["curtailed_kw"] - city["transmission_loss_kw"])
            yield {"start_s": t, "end_s": end, "dt_s": dt, "city": city,
                   "nodes": list(nodes.values()), "assets": assets, "ties": ties}
            t = end
            if boundary < len(boundaries) and t == boundaries[boundary]:
                boundary += 1
