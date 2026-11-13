import math
import unittest
from hypergrid.thermal import ThermalTank
from hypergrid.reactants import (
    RegenerativeFuelCell,
    OXYGEN_PER_HYDROGEN,
    WATER_PER_HYDROGEN,
)
from hypergrid.city import CityModel, default_city


def thermal_spec():
    return {
        "id": "heat1",
        "mass_kg": 1000.0,
        "specific_heat_j_kg_k": 4180.0,
        "initial_temperature_c": 40.0,
        "ambient_c": 20.0,
        "conductance_w_k": 10.0,
        "min_temperature_c": 30.0,
        "max_temperature_c": 90.0,
        "cop": 1.0,
        "priority": 0,
        "heater_electric_kw": [{"time_s": 0, "value": 5.0}],
        "demand_kw_th": [{"time_s": 0, "value": 2.0}],
    }


class ThermalTests(unittest.TestCase):
    def test_hot_boundary_cannot_be_hidden_by_free_cooling(self):
        tank = ThermalTank(1000, 3600, 40, 100, 1000, 30, 45)
        r = tank.step(0, 0, 3600)
        self.assertGreater(r["temperature_c"], 45.0)
        self.assertTrue(r["overtemperature"])
        self.assertEqual(r["dump_kw_th"], 0.0)
        self.assertAlmostEqual(r["balance_residual_kwh_th"], 0.0, places=10)

    def test_passive_cooling_closed_form(self):
        tank = ThermalTank(1000, 4180, 60, 20, 10, 30, 90)
        r = tank.step(0, 0, 3600)
        exact = 20 + 40 * math.exp(-10 * 3600 / (1000 * 4180))
        self.assertAlmostEqual(r["temperature_c"], exact, places=11)
        self.assertAlmostEqual(
            r["ambient_loss_kwh_th"], 1000 * 4180 * (60 - exact) / 3_600_000, places=10
        )
        self.assertAlmostEqual(r["balance_residual_kwh_th"], 0, places=10)

    def test_adiabatic_heat_and_ceiling(self):
        tank = ThermalTank(1000, 3600, 40, 20, 0, 30, 45)
        r = tank.step(10, 0, 3600)
        self.assertAlmostEqual(r["temperature_c"], 45)
        self.assertAlmostEqual(r["dump_kw_th"], 5)
        self.assertAlmostEqual(r["stored_change_kwh_th"], 5)

    def test_depletion_and_passive_loss_below_reserve(self):
        tank = ThermalTank(1000, 3600, 35, 20, 0, 30, 90)
        r = tank.step(0, 10, 3600)
        self.assertAlmostEqual(r["served_kw_th"], 5)
        self.assertAlmostEqual(r["unserved_kw_th"], 5)
        self.assertAlmostEqual(r["temperature_c"], 30)
        cold = ThermalTank(1000, 3600, 30, 0, 10, 30, 90)
        r = cold.step(0, 1, 3600)
        self.assertEqual(r["served_kw_th"], 0)
        self.assertLess(r["temperature_c"], 30)

    def test_city_uses_only_electricity_actually_served(self):
        c = default_city()
        c.update(duration_s=3600, step_s=60)
        c["nodes"] = c["nodes"][:1]
        c["ties"] = []
        n = c["nodes"][0]
        n["loads"] = []
        n["storage"] = []
        n["sources"][0].update(rated_kw=1.0, efficiency=1.0)
        n["thermal"] = [thermal_spec()]
        for r in CityModel(c).intervals():
            a = next(a for a in r["assets"] if a["kind"] == "thermal_storage")
            self.assertEqual(a["served_kw"], 1.0)
            self.assertEqual(a["input_kw_th"], 1.0)
            self.assertAlmostEqual(r["city"]["balance_residual_kw"], 0, places=10)
            self.assertAlmostEqual(a["balance_residual_kwh_th"], 0, places=10)

    def test_step_subdivision_same_constant_inputs(self):
        a = ThermalTank(1000, 4180, 40, 20, 10, 30, 90)
        b = ThermalTank(1000, 4180, 40, 20, 10, 30, 90)
        a.step(5, 2, 3600)
        for _ in range(60):
            b.step(5, 2, 60)
        self.assertAlmostEqual(a.temperature_c, b.temperature_c, places=10)


class ReactantTests(unittest.TestCase):
    def model(self, oxygen=OXYGEN_PER_HYDROGEN, water=WATER_PER_HYDROGEN, leakage=0.0):
        return RegenerativeFuelCell(
            "rfc",
            66.66,
            33.33,
            100,
            100,
            1,
            1,
            0,
            1,
            leakage,
            specific_energy_kwh_kg=33.33,
            oxygen_kg=oxygen,
            water_kg=water,
        )

    def test_closed_cycle_mass_conservation(self):
        rfc = self.model()
        r = rfc.step(33.33, 3600)
        self.assertAlmostEqual(r["hydrogen_kg"], 0)
        self.assertAlmostEqual(r["oxygen_kg"], 0)
        self.assertAlmostEqual(r["mass_balance_residual_kg"], 0, places=12)
        r = rfc.step(-33.33, 3600)
        self.assertAlmostEqual(r["hydrogen_kg"], 1)
        self.assertAlmostEqual(r["oxygen_kg"], OXYGEN_PER_HYDROGEN)
        self.assertAlmostEqual(r["mass_balance_residual_kg"], 0, places=12)

    def test_oxygen_and_water_limits(self):
        self.assertEqual(self.model(oxygen=0).step(10, 3600)["power_kw"], 0)
        self.assertEqual(self.model(water=0).step(-10, 3600)["power_kw"], 0)

    def test_leakage_is_logged_as_mass_leaving(self):
        r = self.model(leakage=0.1).step(0, 3600)
        self.assertAlmostEqual(r["leaked_hydrogen_kg"], 1 - math.exp(-0.1))
        self.assertAlmostEqual(r["mass_balance_residual_kg"], 0, places=12)


if __name__ == "__main__":
    unittest.main()
