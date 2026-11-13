import unittest
from hypergrid.numerics import integrate, reference_benchmarks


class NumericsTests(unittest.TestCase):
    def test_closed_form_and_fourth_order_convergence(self):
        for case in reference_benchmarks():
            with self.subTest(case=case["case"]):
                self.assertLess(case["finest_relative_error"], 0.01)
                self.assertLess(case["absolute_errors"][2], case["absolute_errors"][1])
                for order in case["observed_orders"]:
                    self.assertGreater(order, 3.8)
                    self.assertLess(order, 4.3)

    def test_partial_final_step(self):
        self.assertAlmostEqual(integrate(lambda t, y: (2.0,), (0.0,), 1.0, 0.3)[0], 2.0)

    def test_invalid_derivative(self):
        for rhs in [lambda t, y: (float("nan"),), lambda t, y: ()]:
            with self.assertRaises(ValueError):
                integrate(rhs, (0.0,), 1.0, 0.1)


if __name__ == "__main__":
    unittest.main()
