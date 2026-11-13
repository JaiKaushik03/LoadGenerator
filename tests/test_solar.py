import math
import unittest
from hypergrid.solar import SolarArray


def panel(**kwargs):
    return SolarArray(
        **{
            "series_cells": 60,
            "parallel_strings": 2,
            "photocurrent_ref_a": 8.0,
            "saturation_current_ref_a": 1e-10,
            "series_resistance_cell_ohm": 0.003,
            "shunt_resistance_cell_ohm": 500.0,
            "ideality_factor": 1.3,
            "current_temp_coefficient_a_k": 0.004,
            "bandgap_ev": 1.12,
            **kwargs,
        }
    )


class SolarTests(unittest.TestCase):
    def test_kirchhoff_residual(self):
        p = panel()
        r = p.operating_point(1000.0)
        v = r["array_voltage_v"] / 60
        i = r["array_current_a"] / 2
        iph, i0, a = p.parameters(1000.0, 25.0)
        residual = (
            iph - i0 * math.expm1((v + i * 0.003) / a) - (v + i * 0.003) / 500.0 - i
        )
        self.assertLess(abs(residual), 1e-10)

    def test_mpp_matches_independent_dense_voltage_sweep(self):
        p = panel()
        r = p.operating_point(1000.0)
        sweep = max(
            v * p.cell_current(v) * 120 / 1000
            for v in [r["cell_voc_v"] * j / 2000 for j in range(2001)]
        )
        self.assertLess(abs(r["array_power_kw"] - sweep) / r["array_power_kw"], 0.00001)

    def test_series_parallel_scaling(self):
        a = panel().operating_point(1000.0)
        b = panel(series_cells=120, parallel_strings=4).operating_point(1000.0)
        self.assertAlmostEqual(b["array_voltage_v"], 2 * a["array_voltage_v"])
        self.assertAlmostEqual(b["array_current_a"], 2 * a["array_current_a"])
        self.assertAlmostEqual(b["array_power_kw"], 4 * a["array_power_kw"])

    def test_darkness_dust_and_temperature(self):
        p = panel()
        self.assertEqual(p.operating_point(0.0)["array_power_kw"], 0.0)
        self.assertLess(
            p.operating_point(1000.0, dust_transmission=0.5)["array_power_kw"],
            p.operating_point(1000.0)["array_power_kw"],
        )
        self.assertLess(
            p.operating_point(1000.0, temperature_c=60.0)["cell_voc_v"],
            p.operating_point(1000.0, temperature_c=25.0)["cell_voc_v"],
        )

    def test_invalid_inputs(self):
        for args in [
            {"series_cells": 0},
            {"parallel_strings": True},
            {"ideality_factor": 0},
            {"cell_temperature_c": float("nan")},
        ]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                panel(**args)

    def test_city_generation_uses_diode_solution_and_rating_clip(self):
        from dataclasses import asdict
        from hypergrid.city import default_city, CityModel

        c = default_city()
        c.update(duration_s=60)
        source = c["nodes"][0]["sources"][0]
        source.update(pv=asdict(panel()), rated_kw=0.1, efficiency=0.9)
        row = next(CityModel(c).intervals())
        asset = next(a for a in row["assets"] if a["asset"] == source["id"])
        self.assertAlmostEqual(asset["power_kw"], 0.09)
        self.assertGreater(asset["mppt_clipping_kw"], 0)
        self.assertAlmostEqual(row["city"]["balance_residual_kw"], 0, places=10)


if __name__ == "__main__":
    unittest.main()
