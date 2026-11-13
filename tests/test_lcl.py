import unittest
from hypergrid.lcl import LCLNetwork, default_lcl_network


class LCLTests(unittest.TestCase):
    def test_cascaded_controls_conserve_power_and_limit_reference(self):
        for control in ["droop", "vsm", "dvoc"]:
            c = default_lcl_network()
            c["duration_s"] = 0.04
            c["nodes"][0]["control"] = control
            rows = list(LCLNetwork(c).samples())
            with self.subTest(control=control):
                self.assertLess(
                    max(abs(r["power_balance_residual_w"]) for r in rows), 1e-7
                )
                self.assertLess(
                    max(r["nodes"][0]["current_reference_peak_a"] for r in rows),
                    50.0 + 1e-8,
                )
                self.assertGreater(rows[-1]["nodes"][0]["voltage_phase_rms_v"], 100.0)
                self.assertLess(rows[-1]["nodes"][0]["voltage_phase_rms_v"], 140.0)

    def test_resource_power_envelope(self):
        c = default_lcl_network()
        c["duration_s"] = 0.02
        c["nodes"][0].update(source_power_limit_w=500.0, sink_power_limit_w=0.0)
        for row in LCLNetwork(c).samples():
            self.assertLessEqual(row["input_power_w"], 500.0 + 1e-8)
            self.assertGreaterEqual(row["input_power_w"], -1e-8)

    def test_lcl_step_refinement(self):
        values = []
        for step in [0.00001, 0.000005, 0.0000025]:
            c = default_lcl_network()
            c.update(duration_s=0.02, step_s=step)
            values.append(
                list(LCLNetwork(c).samples())[-1]["nodes"][0]["voltage_phase_rms_v"]
            )
        self.assertLess(abs(values[1] - values[2]) / values[2], 0.01)
        self.assertLess(abs(values[1] - values[2]), abs(values[0] - values[2]))

    def test_missing_filter_and_unsafe_step_rejected(self):
        c = default_lcl_network()
        del c["nodes"][0]["lcl"]["filter_c_f"]
        with self.assertRaises(ValueError):
            LCLNetwork(c)
        c = default_lcl_network()
        c["step_s"] = 0.001
        with self.assertRaises(ValueError):
            LCLNetwork(c)


if __name__ == "__main__":
    unittest.main()
