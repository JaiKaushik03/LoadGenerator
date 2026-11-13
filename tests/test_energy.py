import math
import unittest
from hypergrid.energy import Storage, battery_capacity_kwh


class EnergyTests(unittest.TestCase):
    def test_cell_sizing(self):
        self.assertAlmostEqual(battery_capacity_kwh(250, 9, 3.2, 314), 2260.8)

    def test_discharge_analytic(self):
        s = Storage("pack", 100, 80, 50, 50, discharge_efficiency=0.8)
        r = s.step(20, 3600)
        self.assertAlmostEqual(r["energy_kwh"], 55)
        self.assertAlmostEqual(r["loss_kwh"], 5)
        self.assertAlmostEqual(r["balance_residual_kwh"], 0)

    def test_charge_analytic(self):
        s = Storage("pack", 100, 30, 50, 50, charge_efficiency=0.8)
        r = s.step(-20, 3600)
        self.assertAlmostEqual(r["energy_kwh"], 46)
        self.assertAlmostEqual(r["loss_kwh"], 4)
        self.assertAlmostEqual(r["balance_residual_kwh"], 0)

    def test_reserve_and_ceiling(self):
        s = Storage("pack", 100, 20, 100, 100, 1, 1)
        self.assertAlmostEqual(s.step(100, 3600)["power_kw"], 10)
        self.assertAlmostEqual(s.step(-100, 3600)["power_kw"], -85)

    def test_idle_loss_is_not_replenished_at_reserve(self):
        s = Storage("pack", 100, 10, 100, 100, self_discharge_per_hour=0.1)
        r = s.step(10, 3600)
        self.assertEqual(r["power_kw"], 0)
        self.assertAlmostEqual(r["energy_kwh"], 10 * math.exp(-0.1))
        self.assertAlmostEqual(r["balance_residual_kwh"], 0)

    def test_subdivision_consistency(self):
        a = Storage("pack", 100, 80, 50, 50)
        b = Storage("pack", 100, 80, 50, 50)
        a.step(10, 3600)
        for _ in range(60):
            b.step(10, 60)
        self.assertAlmostEqual(a.energy_kwh, b.energy_kwh)

    def test_invalid_inputs(self):
        for v in [float("nan"), float("inf"), -1, True]:
            with self.subTest(v=v), self.assertRaises(ValueError):
                Storage("bad", v, 0, 1, 1)
        s = Storage("pack", 100, 80, 50, 50)
        for dt in [0, -1, float("inf")]:
            with self.subTest(dt=dt), self.assertRaises(ValueError):
                s.step(1, dt)


if __name__ == "__main__":
    unittest.main()
