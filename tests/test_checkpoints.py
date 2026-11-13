import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from city_cli import run
from hypergrid.city import CityModel, default_city
from hypergrid.checkpoints import writer_lock


def scenario():
    c = default_city()
    c.update(duration_s=600.0, step_s=30.0, output_interval_s=60.0)
    c["telemetry"] = {
        "seed": 42,
        "delay_s": 40.0,
        "jitter_s": 10.0,
        "loss_probability": 0.1,
        "power_noise_std_kw": 0.1,
        "freshness_limit_s": 120.0,
        "attacks": [],
    }
    return c


class CheckpointTests(unittest.TestCase):
    def test_snapshot_restores_rng_queue_and_physical_states(self):
        c = scenario()
        baseline = list(CityModel(c).outputs())
        first = CityModel(c)
        iterator = first.outputs()
        prefix = [next(iterator) for _ in range(4)]
        state = json.loads(json.dumps(first.snapshot()))
        second = CityModel(c)
        second.restore(state)
        self.assertEqual(prefix + list(second.outputs()), baseline)

    def test_recovery_preserves_tail_and_matches_uninterrupted_bytes(self):
        c = scenario()
        original = CityModel.outputs

        def interrupted(model):
            for index, row in enumerate(original(model)):
                if index == 3:
                    raise RuntimeError("simulated interruption")
                yield row

        with tempfile.TemporaryDirectory() as d:
            expected = Path(d) / "expected"
            resumed = Path(d) / "resumed"
            run(c, expected, checkpoint_every=2)
            with (
                patch.object(CityModel, "outputs", interrupted),
                self.assertRaises(RuntimeError),
            ):
                run(c, resumed, checkpoint_every=2)
            result = run(c, resumed, resume=True, checkpoint_every=2)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(
                (expected / "intervals.jsonl").read_bytes(),
                (resumed / "intervals.jsonl").read_bytes(),
            )
            self.assertEqual(len(list(resumed.glob("uncommitted-tail-*.jsonl"))), 1)

    def test_corrupt_prefix_rejected_without_further_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "run"
            c = scenario()
            run(c, folder, checkpoint_every=2)
            path = folder / "intervals.jsonl"
            damaged = b"X" + path.read_bytes()[1:]
            path.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError, "checksum"):
                run(c, folder, resume=True)
            self.assertEqual(path.read_bytes(), damaged)

    def test_writer_lock_prevents_concurrent_generation(self):
        with tempfile.TemporaryDirectory() as d:
            with writer_lock(d), self.assertRaises(RuntimeError):
                with writer_lock(d):
                    pass

    def test_invalid_restore_is_atomic_and_snapshot_is_independent(self):
        model = CityModel(scenario())
        iterator = model.outputs()
        next(iterator)
        state = model.snapshot()
        saved = copy.deepcopy(state)
        next(iterator)
        self.assertEqual(state, saved)
        before = model.snapshot()
        bad = copy.deepcopy(before)
        next(iter(bad["stores"].values()))["energy_kwh"] = -1.0
        with self.assertRaises(ValueError):
            model.restore(bad)
        self.assertEqual(model.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
