"""Seeded synthetic measurement transport; attacks never alter physical truth.

This models a delayed/lossy measurement channel, not an SDN packet network or
trained intrusion detector. Attack labels are ground truth, not input features.
"""

from collections import deque
import heapq
import math
import random
import copy
from .energy import finite


class TelemetryChannel:
    def snapshot(self):
        return copy.deepcopy(
            {
                "rng": self.rng.getstate(),
                "queue": list(self.queue),
                "sequence": self.sequence,
                "latest": self.latest,
                "history": {k: list(v) for k, v in self.history.items()},
                "last_time": self.last_time,
            }
        )

    def restore(self, state, asset_ids, elapsed):
        def tuples(value):
            return tuple(tuples(x) for x in value) if isinstance(value, list) else value

        if set(state) != {"rng", "queue", "sequence", "latest", "history", "last_time"}:
            raise ValueError("Invalid telemetry checkpoint fields")
        finite("last_time", state["last_time"], -1.0, elapsed)
        if (
            isinstance(state["sequence"], bool)
            or not isinstance(state["sequence"], int)
            or state["sequence"] < 0
        ):
            raise ValueError("Invalid packet sequence")
        if len(state["queue"]) > 100000:
            raise ValueError("Invalid queued packet count")
        allowed = {"normal", "bias", "replay"}
        for arrival, seq, asset, source, value, label in state["queue"]:
            if (
                asset not in asset_ids
                or label not in allowed
                or not isinstance(seq, int)
                or not 0 < seq <= state["sequence"]
            ):
                raise ValueError("Invalid queued packet")
            finite("arrival", arrival, 0.0)
            finite("source", source, 0.0, elapsed)
            finite("measurement", value, -math.inf)
        for asset, record in state["latest"].items():
            if asset not in asset_ids or len(record) != 4 or record[2] not in allowed:
                raise ValueError("Invalid latest observation")
            finite("source", record[0], 0.0, elapsed)
            finite("measurement", record[1], -math.inf)
            finite("arrival", record[3], 0.0, elapsed)
        for asset, history in state["history"].items():
            if asset not in asset_ids or len(history) > 1024:
                raise ValueError("Invalid observation history")
            for timestamp, value in history:
                finite("timestamp", timestamp, 0.0, elapsed)
                finite("measurement", value, -math.inf)
        self.rng.setstate(tuples(state["rng"]))
        self.queue = [tuple(x) for x in state["queue"]]
        heapq.heapify(self.queue)
        self.sequence = state["sequence"]
        self.latest = {k: tuple(v) for k, v in state["latest"].items()}
        self.history = {
            k: deque((tuple(x) for x in v), maxlen=1024)
            for k, v in state["history"].items()
        }
        self.last_time = state["last_time"]

    def __init__(self, config):
        allowed = {
            "seed",
            "delay_s",
            "jitter_s",
            "loss_probability",
            "power_noise_std_kw",
            "freshness_limit_s",
            "attacks",
        }
        if set(config) - allowed:
            raise ValueError("Unsupported telemetry setting")
        if isinstance(config["seed"], bool) or not isinstance(config["seed"], int):
            raise ValueError("seed must be integer")
        self.rng = random.Random(config["seed"])
        self.config = copy.deepcopy(config)
        for key in ["delay_s", "jitter_s", "power_noise_std_kw", "freshness_limit_s"]:
            finite(key, config[key])
        finite("loss_probability", config["loss_probability"], 0.0, 1.0)
        for attack in config["attacks"]:
            if set(attack) - {
                "start_s",
                "end_s",
                "kind",
                "targets",
                "bias_kw",
                "replay_age_s",
            }:
                raise ValueError("Unsupported attack parameter")
            finite("start_s", attack["start_s"])
            finite("end_s", attack["end_s"], attack["start_s"])
            if attack["kind"] not in ["drop", "bias", "replay"]:
                raise ValueError("Unknown synthetic attack")
            if not isinstance(attack["targets"], list) or not all(
                isinstance(t, str) for t in attack["targets"]
            ):
                raise ValueError("Attack targets must be asset IDs")
            finite("bias_kw", attack.get("bias_kw", 0.0), -math.inf)
            finite("replay_age_s", attack.get("replay_age_s", 0.0))
        self.queue = []
        self.sequence = 0
        self.latest = {}
        self.history = {}
        self.last_time = -1.0

    def sample(self, time_s, truth):
        finite("time_s", time_s)
        if time_s < self.last_time:
            raise ValueError("Telemetry time must not move backwards")
        self.last_time = time_s
        sent = {}
        for asset, power in sorted(truth.items()):
            finite("power_kw", power, -math.inf)
            history = self.history.setdefault(asset, deque(maxlen=1024))
            attack = next(
                (
                    a
                    for a in self.config["attacks"]
                    if a["start_s"] <= time_s < a["end_s"] and asset in a["targets"]
                ),
                None,
            )
            label = attack["kind"] if attack else "normal"
            value = power + self.rng.gauss(0.0, self.config["power_noise_std_kw"])
            source_time = time_s
            if label == "bias":
                value += attack.get("bias_kw", 0.0)
            if label == "replay" and history:
                cutoff = time_s - attack.get("replay_age_s", 0.0)
                candidate = next(
                    (p for p in reversed(history) if p[0] <= cutoff), history[0]
                )
                source_time, value = candidate
            dropped = (
                label == "drop" or self.rng.random() < self.config["loss_probability"]
            )
            sent[asset] = {"injected_attack": label, "packet_dropped": dropped}
            history.append((time_s, power))
            if not dropped:
                arrival = time_s + max(
                    0.0,
                    self.config["delay_s"]
                    + self.rng.uniform(
                        -self.config["jitter_s"], self.config["jitter_s"]
                    ),
                )
                self.sequence += 1
                heapq.heappush(
                    self.queue,
                    (arrival, self.sequence, asset, source_time, value, label),
                )
                if len(self.queue) > 100000:
                    raise ValueError("Telemetry pending-packet budget exceeded")
        while self.queue and self.queue[0][0] <= time_s:
            arrival, _, asset, source, value, label = heapq.heappop(self.queue)
            self.latest[asset] = (source, value, label, arrival)
        output = {}
        for asset, power in truth.items():
            observation = self.latest.get(asset)
            age = time_s - observation[0] if observation else None
            output[asset] = {
                "ground_truth_power_kw": power,
                "observed_power_kw": observation[1] if observation else None,
                "observation_age_s": age,
                "observation_fresh": age is not None
                and age <= self.config["freshness_limit_s"],
                "received_attack_ground_truth": observation[2] if observation else None,
                **sent[asset],
            }
        return output


def verify_dispatch(power_kw, lower_kw, upper_kw, observation, now_s, max_age_s):
    """Independent envelope/freshness gate; no attack-detection claim."""
    for key, value in [
        ("lower_kw", lower_kw),
        ("upper_kw", upper_kw),
        ("now_s", now_s),
        ("max_age_s", max_age_s),
    ]:
        finite(key, value, -math.inf if key in ["lower_kw", "upper_kw"] else 0.0)
    if lower_kw > upper_kw:
        raise ValueError("Invalid dispatch envelope")
    if (
        isinstance(power_kw, bool)
        or not isinstance(power_kw, (int, float))
        or not math.isfinite(power_kw)
    ):
        return False, "nonfinite_command"
    if not lower_kw <= power_kw <= upper_kw:
        return False, "outside_power_envelope"
    if observation is None:
        return False, "missing_observation"
    source = observation.get("source_time_s")
    value = observation.get("power_kw")
    if (
        isinstance(source, bool)
        or not isinstance(source, (int, float))
        or not math.isfinite(source)
        or not 0 <= now_s - source <= max_age_s
    ):
        return False, "stale_or_invalid_time"
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        return False, "invalid_observation"
    return True, "accepted"
