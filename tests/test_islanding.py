import copy
import math
import unittest
from hypergrid.emt import default_network, EMTNetwork
from hypergrid.lcl import default_lcl_network, LCLNetwork


class IslandingTests(unittest.TestCase):
    def test_open_line_preserves_and_dissipates_inductor_energy(self):
        for factory, model_class in [
            (default_network, EMTNetwork),
            (default_lcl_network, LCLNetwork),
        ]:
            config = factory()
            config["duration_s"] = 0.02
            config["nodes"].append(copy.deepcopy(config["nodes"][0]))
            config["nodes"][1].update(id="isru", load_r_ohm=15.0)
            config["lines"] = [
                {
                    "id": "tie",
                    "a": "habitat",
                    "b": "isru",
                    "r_ohm": 0.2,
                    "l_h": 0.002,
                    "open_snubber_r_ohm": 2.0,
                    "closed_schedule": [
                        {"time_s": 0.0, "value": 1},
                        {"time_s": 0.01, "value": 0},
                    ],
                }
            ]
            rows = list(model_class(config).samples())
            opened = [r for r in rows if r["time_s"] >= 0.01]
            with self.subTest(model=model_class.__name__):
                self.assertFalse(opened[0]["lines"][0]["closed"])
                self.assertGreater(opened[0]["lines"][0]["inductor_energy_j"], 0.0)
                initial = opened[0]["lines"][0]["inductor_energy_j"]
                last = opened[-1]
                expected = initial * math.exp(
                    -2 * 2.0 / 0.002 * (last["time_s"] - opened[0]["time_s"])
                )
                self.assertLess(
                    abs(last["lines"][0]["inductor_energy_j"] - expected)
                    / max(initial, 1e-12),
                    0.00001,
                )
                self.assertLess(
                    max(abs(r["power_balance_residual_w"]) for r in rows), 1e-6
                )


if __name__ == "__main__":
    unittest.main()
