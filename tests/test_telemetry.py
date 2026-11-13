import copy
import unittest
from hypergrid.telemetry import TelemetryChannel, verify_dispatch


def config():
    return {
        "seed": 42,
        "delay_s": 0.0,
        "jitter_s": 0.0,
        "loss_probability": 0.0,
        "power_noise_std_kw": 0.0,
        "freshness_limit_s": 1.0,
        "attacks": [],
    }


class TelemetryTests(unittest.TestCase):
    def test_delay_and_stale_observation(self):
        c = config()
        c["delay_s"] = 2.0
        c["freshness_limit_s"] = 1.0
        channel = TelemetryChannel(c)
        self.assertIsNone(channel.sample(0.0, {"x": 10.0})["x"]["observed_power_kw"])
        r = channel.sample(2.0, {"x": 20.0})["x"]
        self.assertEqual(r["observed_power_kw"], 10.0)
        self.assertFalse(r["observation_fresh"])

    def test_bias_drop_replay_preserve_truth(self):
        c = config()
        c["attacks"] = [
            {
                "start_s": 1.0,
                "end_s": 2.0,
                "kind": "bias",
                "targets": ["x"],
                "bias_kw": 100.0,
            },
            {
                "start_s": 2.0,
                "end_s": 3.0,
                "kind": "replay",
                "targets": ["x"],
                "replay_age_s": 2.0,
            },
            {"start_s": 3.0, "end_s": 4.0, "kind": "drop", "targets": ["x"]},
        ]
        channel = TelemetryChannel(c)
        truth = {"x": 10.0}
        saved = copy.deepcopy(truth)
        channel.sample(0.0, truth)
        r = channel.sample(1.0, truth)["x"]
        self.assertEqual(r["observed_power_kw"], 110.0)
        r = channel.sample(2.0, {"x": 20.0})["x"]
        self.assertEqual(r["observed_power_kw"], 10.0)
        self.assertEqual(r["observation_age_s"], 2.0)
        self.assertTrue(channel.sample(3.0, truth)["x"]["packet_dropped"])
        self.assertEqual(truth, saved)

    def test_seed_reproducibility(self):
        c = config()
        c.update(jitter_s=0.2, power_noise_std_kw=0.2, loss_probability=0.2)
        a, b = TelemetryChannel(c), TelemetryChannel(c)
        self.assertEqual(
            [a.sample(t, {"x": 10.0}) for t in range(20)],
            [b.sample(t, {"x": 10.0}) for t in range(20)],
        )

    def test_unsafe_actions_rejected(self):
        obs = {"source_time_s": 10.0, "power_kw": 2.0}
        self.assertEqual(
            verify_dispatch(3.0, -5.0, 5.0, obs, 10.0, 1.0), (True, "accepted")
        )
        for value, observation, now in [
            (100.0, obs, 10.0),
            (float("nan"), obs, 10.0),
            (2.0, None, 10.0),
            (2.0, obs, 12.0),
        ]:
            self.assertFalse(
                verify_dispatch(value, -5.0, 5.0, observation, now, 1.0)[0]
            )
        self.assertTrue(verify_dispatch(-2.0, -5.0, -1.0, obs, 10.0, 1.0)[0])
        self.assertFalse(
            verify_dispatch(
                2.0, -5.0, 5.0, {"source_time_s": True, "power_kw": 2.0}, 1.0, 1.0
            )[0]
        )

    def test_city_measurement_attacks_do_not_change_physics(self):
        from hypergrid.city import CityModel, default_city

        clean = default_city()
        clean.update(duration_s=120.0)
        corrupted = copy.deepcopy(clean)
        corrupted["telemetry"] = config()
        corrupted["telemetry"]["attacks"] = [
            {
                "start_s": 0.0,
                "end_s": 120.0,
                "kind": "bias",
                "targets": ["solar0"],
                "bias_kw": 100.0,
            }
        ]
        a = list(CityModel(clean).intervals())
        b = list(CityModel(corrupted).intervals())
        self.assertEqual([r["city"] for r in a], [r["city"] for r in b])
        source = next(s for s in b[0]["assets"] if s["asset"] == "solar0")
        self.assertEqual(
            source["observed_power_kw"], source["ground_truth_power_kw"] + 100.0
        )


if __name__ == "__main__":
    unittest.main()
