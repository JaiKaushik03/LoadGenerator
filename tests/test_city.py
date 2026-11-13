import copy
import unittest
from hypergrid.city import CityModel, default_city, make_storage


class CityTests(unittest.TestCase):
    def test_default_city_conserves_energy(self):
        c = default_city()
        c["duration_s"] = 90000
        records = list(CityModel(c).intervals())
        self.assertEqual(records[-1]["end_s"], 90000)
        for r in records:
            self.assertAlmostEqual(r["city"]["balance_residual_kw"], 0, places=9)
            self.assertAlmostEqual(
                r["city"]["storage_balance_residual_kwh"], 0, places=9
            )
            self.assertGreaterEqual(r["city"]["unserved_kw"], 0)
            for n in r["nodes"]:
                self.assertAlmostEqual(
                    n["generation_kw"] + n["storage_kw"] + n["import_kw"],
                    n["served_kw"] + n["curtailed_kw"] + n["export_kw"],
                    places=9,
                )

    def test_priority_shedding(self):
        c = default_city()
        c["nodes"] = c["nodes"][1:2]
        c["ties"] = []
        n = c["nodes"][0]
        n["storage"] = []
        n["sources"][0]["rated_kw"] = 15
        n["sources"][0]["efficiency"] = 1
        c["duration_s"] = 60
        r = next(CityModel(c).intervals())
        loads = [a for a in r["assets"] if a["kind"] == "load"]
        self.assertEqual([a["served_kw"] for a in loads], [10, 5])

    def test_tie_capacity_and_losses(self):
        c = default_city()
        c["nodes"] = c["nodes"][:2]
        for n in c["nodes"]:
            n["storage"] = []
            n["sources"][0]["efficiency"] = 1
        c["nodes"][0]["sources"][0]["rated_kw"] = 100
        c["nodes"][1]["sources"][0]["rated_kw"] = 0
        c["ties"] = c["ties"][:1]
        c["ties"][0].update(capacity_kw=10, loss_fraction=0.1)
        c["duration_s"] = 60
        r = next(CityModel(c).intervals())
        self.assertAlmostEqual(r["ties"][0]["sent_kw"], 10)
        self.assertAlmostEqual(r["ties"][0]["received_kw"], 9)
        self.assertAlmostEqual(r["city"]["balance_residual_kw"], 0)

    def test_event_boundary_not_quantized_to_step(self):
        c = default_city()
        c.update(duration_s=100, step_s=60)
        c["nodes"][0]["sources"][0]["availability"] = [
            {"time_s": 0, "value": 1},
            {"time_s": 17, "value": 0},
        ]
        r = list(CityModel(c).intervals())
        self.assertEqual(r[0]["end_s"], 17)
        self.assertEqual(sum(x["dt_s"] for x in r), 100)
        self.assertEqual(r[1]["nodes"][0]["generation_kw"], 0)

    def test_islanding(self):
        c = default_city()
        c["duration_s"] = 60
        for tie in c["ties"]:
            tie["availability"][0]["value"] = 0
        self.assertTrue(
            all(t["sent_kw"] == 0 for t in next(CityModel(c).intervals())["ties"])
        )

    def test_repeatable_and_input_unchanged(self):
        c = default_city()
        c["duration_s"] = 120
        original = copy.deepcopy(c)
        self.assertEqual(list(CityModel(c).intervals()), list(CityModel(c).intervals()))
        self.assertEqual(c, original)

    def test_resource_capacity_equations(self):
        s = default_city()["nodes"][0]["storage"][0]
        for params, expected in [
            (
                {
                    "kind": "supercapacitor",
                    "capacitance_f": 7200,
                    "maximum_voltage_v": 100,
                },
                10,
            ),
            (
                {"kind": "flywheel", "inertia_kg_m2": 720, "maximum_speed_rad_s": 1000},
                100,
            ),
            (
                {
                    "kind": "regenerative_fuel_cell",
                    "hydrogen_capacity_kg": 10,
                    "hydrogen_specific_energy_kwh_kg": 33.33,
                },
                333.3,
            ),
        ]:
            with self.subTest(kind=params["kind"]):
                self.assertAlmostEqual(
                    make_storage({**s, **params}).capacity_kwh, expected
                )

    def test_bad_topology_and_nonfinite_rejected(self):
        for change in ["duplicate", "missing_node", "nan", "schedule", "fidelity"]:
            c = default_city()
            if change == "duplicate":
                c["nodes"][1]["id"] = c["nodes"][0]["id"]
            elif change == "missing_node":
                c["ties"][0]["a"] = "missing"
            elif change == "nan":
                c["step_s"] = float("nan")
            elif change == "schedule":
                c["nodes"][0]["loads"][0]["demand"][0]["time_s"] = 5
            else:
                c["fidelity"] = "switched"
            with self.subTest(change=change), self.assertRaises(ValueError):
                CityModel(c)

    def test_unsupported_parameters_are_not_silently_ignored(self):
        for where in ["config", "storage", "load", "tie"]:
            c = default_city()
            target = {
                "config": c,
                "storage": c["nodes"][0]["storage"][0],
                "load": c["nodes"][0]["loads"][0],
                "tie": c["ties"][0],
            }[where]
            target["unsupported_parameter"] = 17
            with self.subTest(where=where), self.assertRaises(ValueError):
                CityModel(c)


if __name__ == "__main__":
    unittest.main()
