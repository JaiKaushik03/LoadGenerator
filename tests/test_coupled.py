import unittest
from hypergrid.city import default_city
from hypergrid.emt import default_network
from hypergrid.coupled import CoupledModel


def scenario():
    city = default_city()
    city.update(duration_s=0.04, step_s=0.01)
    city["nodes"] = city["nodes"][:1]
    city["ties"] = []
    n = city["nodes"][0]
    n["sources"][0]["rated_kw"] = 0
    n["loads"] = [
        {"id": "load", "priority": 0, "demand": [{"time_s": 0, "value": 2.16}]}
    ]
    emt = default_network()
    emt["duration_s"] = 0.04
    emt["nodes"][0]["id"] = n["id"]
    return city, emt


class CoupledTests(unittest.TestCase):
    def test_actual_port_energy_depletes_battery(self):
        city, emt = scenario()
        model = CoupledModel(city, emt, 0.01)
        store = next(iter(model.city.stores.values()))
        before = store.energy_kwh
        rows = list(model.intervals())
        self.assertEqual(len(rows), 4)
        self.assertLess(store.energy_kwh, before)
        for r in rows:
            self.assertLess(abs(r["electrical_balance_residual_j"]), 0.001)
            self.assertLess(abs(r["nodes"][0]["resource_balance_residual_kw"]), 1e-10)
        loss = sum(
            s["loss_kwh"] for r in rows for n in r["nodes"] for s in n["storage"]
        )
        port = sum(r["port_energy_j"] for r in rows) / 3_600_000
        self.assertAlmostEqual(before - store.energy_kwh, port + loss, places=10)

    def test_empty_resources_cannot_supply_ac_power(self):
        city, emt = scenario()
        city["nodes"][0]["storage"] = []
        rows = list(CoupledModel(city, emt, 0.01).intervals())
        self.assertTrue(all(abs(r["port_energy_j"]) < 1e-10 for r in rows))
        # Initial capacitor/inductor energy can still power the load briefly.
        self.assertGreater(sum(r["load_energy_j"] for r in rows), 0.0)

    def test_unmapped_node_rejected(self):
        city, emt = scenario()
        emt["nodes"][0]["id"] = "other"
        with self.assertRaises(ValueError):
            CoupledModel(city, emt, 0.01)

    def test_heat_receives_only_actual_ac_service(self):
        from test_resource_physics import thermal_spec

        city, emt = scenario()
        city["nodes"][0]["thermal"] = [thermal_spec()]
        rows = list(CoupledModel(city, emt, 0.01).intervals())
        for row in rows:
            node = row["nodes"][0]
            tank = next(a for a in node["loads"] if a["kind"] == "thermal_storage")
            self.assertAlmostEqual(tank["input_kw_th"], tank["served_kw"])
            self.assertLessEqual(
                sum(a["served_kw"] for a in node["loads"]), node["mean_load_kw"] + 1e-9
            )
            self.assertLess(abs(tank["balance_residual_kwh_th"]), 1e-8)


if __name__ == "__main__":
    unittest.main()
