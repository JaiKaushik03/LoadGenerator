import unittest
from hypergrid.city import default_city, CityModel


class SamplingTests(unittest.TestCase):
    def test_coarse_output_conserves_energy_and_retains_end_state(self):
        c = default_city()
        c.update(duration_s=620.0, step_s=60.0)
        fine = list(CityModel(c).intervals())
        c["output_interval_s"] = 300.0
        coarse = list(CityModel(c).outputs())
        self.assertEqual([r["end_s"] for r in coarse], [300.0, 600.0, 620.0])
        for key in ["generation_kw", "served_kw", "unserved_kw", "storage_kw"]:
            self.assertAlmostEqual(
                sum(r["city"][key] * r["dt_s"] for r in fine),
                sum(r["city"][key] * r["dt_s"] for r in coarse),
                places=6,
            )
        self.assertAlmostEqual(
            fine[-1]["assets"][1]["energy_kwh"], coarse[-1]["assets"][1]["energy_kwh"]
        )

    def test_events_are_integrated_without_moving_output_grid(self):
        c = default_city()
        c.update(duration_s=100.0, step_s=10.0, output_interval_s=30.0)
        c["nodes"][0]["sources"][0]["availability"] = [
            {"time_s": 0.0, "value": 1.0},
            {"time_s": 17.0, "value": 0.0},
        ]
        rows = list(CityModel(c).outputs())
        self.assertEqual([r["end_s"] for r in rows], [30.0, 60.0, 90.0, 100.0])
        source = next(a for a in rows[0]["assets"] if a["asset"] == "solar0")
        self.assertAlmostEqual(source["power_kw"], 150.0 * 0.97 * 17.0 / 30.0)
        self.assertGreater(rows[0]["integration_intervals"], 3)

    def test_floating_point_steps_do_not_create_tiny_tail(self):
        c = default_city()
        c.update(duration_s=1.0, step_s=0.1, output_interval_s=0.3)
        rows = list(CityModel(c).outputs())
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["end_s"], 1.0)
        self.assertTrue(all(r["dt_s"] > 0.0 for r in rows))

    def test_output_cannot_claim_resolution_finer_than_integration(self):
        c = default_city()
        c["output_interval_s"] = 1.0
        with self.assertRaises(ValueError):
            CityModel(c)


if __name__ == "__main__":
    unittest.main()
