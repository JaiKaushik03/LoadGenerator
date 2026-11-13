import copy
import math
import unittest
from hypergrid.emt import EMTNetwork, default_network


class EMTTests(unittest.TestCase):
    def test_transformer_referred_network_preserves_power(self):
        c = default_network()
        c.update(duration_s=0.01, step_s=0.000005)
        c["nodes"].append(copy.deepcopy(c["nodes"][0]))
        c["nodes"][1].update(id="isru", load_r_ohm=15.0)
        ratio = 3000.0 / (math.sqrt(3) * 120.0)
        c["lines"] = [
            {
                "id": "hv",
                "a": "habitat",
                "b": "isru",
                "r_ohm": 10.0,
                "l_h": 0.02,
                "ratio_a": ratio,
                "ratio_b": ratio,
            }
        ]
        rows = list(EMTNetwork(c).samples())
        self.assertLess(max(abs(r["power_balance_residual_w"]) for r in rows), 1e-6)

    def test_all_primary_controls_have_finite_balanced_trajectories(self):
        for control in ["droop", "vsm", "dvoc"]:
            c = default_network()
            c["duration_s"] = 0.04
            c["nodes"][0]["control"] = control
            with self.subTest(control=control):
                rows = list(EMTNetwork(c).samples())
                self.assertAlmostEqual(rows[-1]["time_s"], 0.04)
                self.assertLess(
                    max(abs(r["power_balance_residual_w"]) for r in rows), 1e-7
                )
                self.assertTrue(
                    all(
                        math.isfinite(n["voltage_phase_rms_v"])
                        for r in rows
                        for n in r["nodes"]
                    )
                )

    def test_passive_network_integrated_energy(self):
        c = default_network()
        c.update(duration_s=0.02, output_interval_s=0.00002)
        c["nodes"][0]["source_enabled"] = False
        rows = list(EMTNetwork(c).samples())
        integral = sum(
            (b["time_s"] - a["time_s"])
            * 0.5
            * (
                a["load_power_w"]
                + a["resistive_loss_w"]
                + b["load_power_w"]
                + b["resistive_loss_w"]
            )
            for a, b in zip(rows, rows[1:])
        )
        released = rows[0]["stored_energy_j"] - rows[-1]["stored_energy_j"]
        self.assertGreater(released, 0.0)
        self.assertLess(abs(integral - released) / released, 0.001)

    def test_timestep_refinement_below_one_percent(self):
        values = []
        for dt in [0.00004, 0.00002, 0.00001]:
            c = default_network()
            c.update(duration_s=0.04, step_s=dt, output_interval_s=0.001)
            values.append(
                list(EMTNetwork(c).samples())[-1]["nodes"][0]["voltage_phase_rms_v"]
            )
        self.assertLess(abs(values[1] - values[2]) / abs(values[2]), 0.01)
        self.assertLess(abs(values[1] - values[2]), abs(values[0] - values[2]))

    def test_interconnected_nodes_conserve_power(self):
        c = default_network()
        c["duration_s"] = 0.02
        c["nodes"].append(copy.deepcopy(c["nodes"][0]))
        c["nodes"][1].update(id="isru", load_r_ohm=15.0)
        c["lines"] = [
            {"id": "line1", "a": "habitat", "b": "isru", "r_ohm": 0.2, "l_h": 0.002}
        ]
        rows = list(EMTNetwork(c).samples())
        self.assertLess(max(abs(r["power_balance_residual_w"]) for r in rows), 1e-7)

    def test_invalid_step_and_dc_ac_profile(self):
        for change in ["step", "voltage", "topology"]:
            c = default_network()
            if change == "step":
                c["step_s"] = 0.01
                c["output_interval_s"] = 0.01
            elif change == "voltage":
                c["nodes"][0]["dc_voltage_v"] = 120.0
            else:
                c["lines"] = [
                    {
                        "id": "x",
                        "a": "habitat",
                        "b": "missing",
                        "r_ohm": 1.0,
                        "l_h": 0.1,
                    }
                ]
            with self.subTest(change=change), self.assertRaises(ValueError):
                EMTNetwork(c)

    def test_passive_voltage_matches_closed_form_rlc(self):
        c = default_network()
        c["duration_s"] = 0.003
        c["nodes"][0]["source_enabled"] = False
        n = c["nodes"][0]
        a = n["source_r_ohm"] / n["source_l_h"] + 1 / (n["load_r_ohm"] * n["bus_c_f"])
        b = (1 + n["source_r_ohm"] / n["load_r_ohm"]) / (n["source_l_h"] * n["bus_c_f"])
        beta = math.sqrt(b - a * a / 4)
        v0 = math.sqrt(2) * n["voltage_phase_rms_v"]
        bcoef = (-v0 / (n["load_r_ohm"] * n["bus_c_f"]) + a * v0 / 2) / beta
        t = c["duration_s"]
        exact = math.exp(-a * t / 2) * (
            v0 * math.cos(beta * t) + bcoef * math.sin(beta * t)
        )
        result = list(EMTNetwork(c).samples())[-1]["nodes"][0]
        self.assertLess(abs(result["voltage_alpha_v"] - exact) / abs(exact), 0.00001)
        self.assertAlmostEqual(
            result["voltage_a_v"] + result["voltage_b_v"] + result["voltage_c_v"],
            0.0,
            places=10,
        )

    def test_source_power_envelope_is_enforced(self):
        c = default_network()
        c["duration_s"] = 0.02
        c["nodes"][0].update(source_power_limit_w=100.0, sink_power_limit_w=0.0)
        for r in EMTNetwork(c).samples():
            self.assertLessEqual(r["input_power_w"], 100.0 + 1e-8)
            self.assertGreaterEqual(r["input_power_w"], -1e-8)


if __name__ == "__main__":
    unittest.main()
