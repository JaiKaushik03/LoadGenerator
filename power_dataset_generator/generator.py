"""Synthetic time-series generator used by the GUI prototype.

This module intentionally separates signal generation from the GUI so a real
MATLAB/Simulink/PSCAD adapter can later replace SyntheticPowerSystemGenerator
without redesigning the user interface or Excel export pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Generator, Iterable, Tuple

import numpy as np

from config import DATA_COLUMNS


@dataclass
class GenerationPlan:
    requested_rows: int
    sampling_rate_hz: int
    simulation_duration_s: float

    @property
    def samples_per_simulation(self) -> int:
        return max(1, int(round(self.sampling_rate_hz * self.simulation_duration_s)))

    @property
    def simulations_required(self) -> int:
        return int(math.ceil(self.requested_rows / self.samples_per_simulation))


class SyntheticPowerSystemGenerator:
    """Generate deterministic, physically-inspired demo signals.

    The model is intentionally transparent rather than claiming high-fidelity
    electrical simulation. Replace this class with a real simulator adapter for
    research data.
    """

    def __init__(self, config: Dict):
        self.cfg = dict(config)
        self.plan = GenerationPlan(
            requested_rows=int(self.cfg["rows"]),
            sampling_rate_hz=int(self.cfg["sampling_rate_hz"]),
            simulation_duration_s=float(self.cfg["simulation_duration_s"]),
        )

    def _validate(self) -> None:
        c = self.cfg
        if not (1 <= int(c["rows"]) <= 1_000_000):
            raise ValueError("Excel prototype supports 1 to 1,000,000 data rows per workbook.")
        if int(c["sampling_rate_hz"]) <= 0:
            raise ValueError("Sampling rate must be greater than zero.")
        if float(c["simulation_duration_s"]) <= 0:
            raise ValueError("Simulation duration must be greater than zero.")
        if not (0 < float(c["power_factor"]) <= 1.0):
            raise ValueError("Power factor must be > 0 and <= 1.0.")
        if float(c["load_pct"]) < 0:
            raise ValueError("Load level cannot be negative.")
        for key in ("fault_start_s", "fault_duration_s", "cyber_start_s", "cyber_duration_s"):
            if float(c[key]) < 0:
                raise ValueError(f"{key} cannot be negative.")

    @staticmethod
    def _fault_phases(fault_type: str) -> Tuple[bool, bool, bool]:
        f = fault_type.upper()
        if f.startswith("ABC"):
            return True, True, True
        # For AB-G etc., the letters before optional -G indicate phases.
        base = f.replace("-G", "").replace("G", "")
        return "A" in base, "B" in base, "C" in base

    def _base_signals(self, t: np.ndarray, sim_index: int, rng: np.random.Generator) -> Dict[str, np.ndarray]:
        c = self.cfg
        f = float(c["frequency_hz"])
        omega = 2.0 * np.pi * f
        load = float(c["load_pct"]) / 100.0
        pf = float(c["power_factor"])

        # Demo operating-point modifiers.
        grid_factor = {"Weak": 0.985, "Normal": 1.0, "Strong": 1.010}.get(str(c["grid_strength"]), 1.0)
        feeder_drop = max(0.0, 1.0 - 0.25 * float(c["feeder_impedance_pu"]) * max(load, 0.0))
        vrms = float(c["nominal_voltage_rms_v"]) * grid_factor * feeder_drop
        irms = float(c["nominal_current_rms_a"]) * max(load, 0.01)
        vpk = vrms * math.sqrt(2.0)
        ipk = irms * math.sqrt(2.0)

        # Current lags voltage according to PF for the synthetic baseline.
        phi = math.acos(min(max(pf, 1e-6), 1.0))
        phase = sim_index * 0.003  # tiny deterministic run-to-run phase shift

        va = vpk * np.sin(omega * t + phase)
        vb = vpk * np.sin(omega * t - 2.0 * np.pi / 3.0 + phase)
        vc = vpk * np.sin(omega * t + 2.0 * np.pi / 3.0 + phase)
        ia = ipk * np.sin(omega * t - phi + phase)
        ib = ipk * np.sin(omega * t - 2.0 * np.pi / 3.0 - phi + phase)
        ic = ipk * np.sin(omega * t + 2.0 * np.pi / 3.0 - phi + phase)

        noise_fraction = float(c["natural_noise_pct"]) / 100.0
        if noise_fraction > 0:
            va += rng.normal(0.0, max(abs(vpk) * noise_fraction, 1e-12), len(t))
            vb += rng.normal(0.0, max(abs(vpk) * noise_fraction, 1e-12), len(t))
            vc += rng.normal(0.0, max(abs(vpk) * noise_fraction, 1e-12), len(t))
            ia += rng.normal(0.0, max(abs(ipk) * noise_fraction, 1e-12), len(t))
            ib += rng.normal(0.0, max(abs(ipk) * noise_fraction, 1e-12), len(t))
            ic += rng.normal(0.0, max(abs(ipk) * noise_fraction, 1e-12), len(t))

        # DC side contains low ripple and responds mildly to load.
        vdc0 = float(c["vdc_v"]) * (1.0 - 0.015 * max(load - 0.7, 0.0))
        idc0 = float(c["idc_a"]) * max(load, 0.05)
        vdc = vdc0 + 0.004 * vdc0 * np.sin(2 * omega * t)
        idc = idc0 + 0.01 * max(idc0, 1e-9) * np.sin(2 * omega * t - 0.2)

        # Three-phase real/reactive power estimate from selected RMS operating point.
        p0 = 3.0 * vrms * irms * pf
        q0 = 3.0 * vrms * irms * math.sin(phi)
        p = np.full_like(t, p0, dtype=float)
        q = np.full_like(t, q0, dtype=float)
        frequency = np.full_like(t, f, dtype=float)

        return {
            "Va": va, "Vb": vb, "Vc": vc,
            "Ia": ia, "Ib": ib, "Ic": ic,
            "Vdc": vdc, "Idc": idc,
            "P": p, "Q": q, "Frequency": frequency,
        }

    def _apply_fault(self, signals: Dict[str, np.ndarray], t: np.ndarray) -> np.ndarray:
        c = self.cfg
        active = np.zeros(len(t), dtype=bool)
        if not bool(c["fault_enabled"]):
            return active

        start = float(c["fault_start_s"])
        end = start + float(c["fault_duration_s"])
        active = (t >= start) & (t < end)
        if not np.any(active):
            return active

        a, b, cc = self._fault_phases(str(c["fault_type"]))
        # Lower fault resistance => stronger disturbance. Bounded for numerical stability.
        rf = max(float(c["fault_resistance_ohm"]), 0.001)
        strength = 1.0 / (1.0 + rf / 5.0)  # 0..~1 synthetic severity relation
        voltage_factor = max(0.08, 1.0 - 0.80 * strength)
        current_factor = 1.0 + 4.0 * strength

        for phase, enabled in zip(("A", "B", "C"), (a, b, cc)):
            if enabled:
                signals[f"V{phase.lower()}"][active] *= voltage_factor
                signals[f"I{phase.lower()}"][active] *= current_factor
            else:
                # Small cross-coupling on healthy phases.
                signals[f"V{phase.lower()}"][active] *= (1.0 - 0.05 * strength)
                signals[f"I{phase.lower()}"][active] *= (1.0 + 0.10 * strength)

        # DC and system-level response.
        signals["Vdc"][active] *= (1.0 - 0.08 * strength)
        signals["Idc"][active] *= (1.0 + 0.20 * strength)
        signals["Frequency"][active] -= 0.08 * strength
        signals["P"][active] *= (1.0 - 0.15 * strength)
        signals["Q"][active] *= (1.0 + 0.25 * strength)
        return active

    def _apply_cyber(self, signals: Dict[str, np.ndarray], t: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        c = self.cfg
        active = np.zeros(len(t), dtype=bool)
        if not bool(c["cyber_enabled"]):
            return active

        target = str(c["cyber_target"])
        if target not in signals:
            return active

        start = float(c["cyber_start_s"])
        duration = float(c["cyber_duration_s"])
        end = start + duration
        active = (t >= start) & (t < end)
        idx = np.where(active)[0]
        if len(idx) == 0:
            return active

        x = signals[target]
        attack = str(c["cyber_type"])
        mag = float(c["cyber_magnitude_pct"]) / 100.0

        if attack == "Bias":
            reference = max(float(np.nanstd(x)), float(np.nanmean(np.abs(x))), 1.0)
            x[idx] += mag * reference
        elif attack == "Scaling":
            x[idx] *= (1.0 + mag)
        elif attack == "Ramp":
            relative_t = t[idx] - start
            rate = float(c["cyber_ramp_pct_per_s"]) / 100.0
            reference = max(float(np.nanstd(x)), float(np.nanmean(np.abs(x))), 1.0)
            x[idx] += rate * relative_t * reference
        elif attack == "Noise":
            reference = max(float(np.nanstd(x)), float(np.nanmean(np.abs(x))), 1.0)
            x[idx] += rng.normal(0.0, mag * reference, len(idx))
        elif attack == "Stuck-at":
            frozen = x[idx[0] - 1] if idx[0] > 0 else x[idx[0]]
            x[idx] = frozen
        elif attack == "Replay":
            delay_samples = max(1, int(round(float(c["cyber_replay_delay_s"]) * int(c["sampling_rate_hz"]))))
            source_idx = np.maximum(idx - delay_samples, 0)
            x[idx] = x[source_idx]
        elif attack == "Spike":
            # A small set of samples receives high-amplitude corruption.
            count = max(1, min(len(idx), int(math.ceil(len(idx) * 0.01))))
            spike_idx = idx[np.linspace(0, len(idx) - 1, count, dtype=int)]
            reference = max(float(np.nanstd(x)), float(np.nanmean(np.abs(x))), 1.0)
            x[spike_idx] += np.sign(x[spike_idx] + 1e-12) * mag * reference * 5.0
        elif attack == "Intermittent":
            on_s = max(float(c["cyber_intermit_on_s"]), 1e-6)
            off_s = max(float(c["cyber_intermit_off_s"]), 0.0)
            period = on_s + off_s
            local = t - start
            intermittent = active & ((np.mod(local, period)) < on_s)
            active = intermittent
            idx = np.where(active)[0]
            reference = max(float(np.nanstd(x)), float(np.nanmean(np.abs(x))), 1.0)
            x[idx] += mag * reference

        signals[target] = x
        return active

    def _apply_communication(self, signals: Dict[str, np.ndarray], rng: np.random.Generator) -> np.ndarray:
        c = self.cfg
        n = len(next(iter(signals.values())))
        active = np.zeros(n, dtype=bool)
        if not bool(c["comm_enabled"]):
            return active
        active[:] = True

        sr = int(c["sampling_rate_hz"])
        delay_samples = max(0, int(round(float(c["delay_ms"]) * sr / 1000.0)))
        jitter_samples = max(0, int(round(float(c["jitter_ms"]) * sr / 1000.0)))
        loss_p = min(max(float(c["packet_loss_pct"]) / 100.0, 0.0), 1.0)
        repeat_p = min(max(float(c["repeat_sample_pct"]) / 100.0, 0.0), 1.0)
        bits = int(c["quantization_bits"])

        for key, x0 in list(signals.items()):
            x = x0.copy()
            if delay_samples > 0:
                shifted = np.empty_like(x)
                shifted[:delay_samples] = x[0]
                shifted[delay_samples:] = x[:-delay_samples]
                x = shifted

            if jitter_samples > 0:
                offsets = rng.integers(-jitter_samples, jitter_samples + 1, size=n)
                src = np.clip(np.arange(n) - offsets, 0, n - 1)
                x = x[src]

            if repeat_p > 0 and n > 1:
                rep = rng.random(n) < repeat_p
                rep[0] = False
                inds = np.where(rep)[0]
                x[inds] = x[inds - 1]

            if bits < 16 and bits > 1:
                finite = x[np.isfinite(x)]
                if finite.size:
                    xmin, xmax = float(np.min(finite)), float(np.max(finite))
                    if xmax > xmin:
                        levels = (2 ** bits) - 1
                        x = np.round((x - xmin) / (xmax - xmin) * levels) / levels * (xmax - xmin) + xmin

            if loss_p > 0:
                lost = rng.random(n) < loss_p
                x[lost] = np.nan

            signals[key] = x

        return active

    def _labels(self, fault_active: np.ndarray, cyber_active: np.ndarray, comm_active: np.ndarray) -> np.ndarray:
        labels = np.full(len(fault_active), "Normal", dtype=object)
        labels[comm_active] = "Communication"
        labels[fault_active] = "Fault"
        labels[cyber_active] = "Cyberattack"
        labels[fault_active & cyber_active] = "Combined"
        return labels

    def generate_simulation(self, sim_index: int, max_rows: int | None = None) -> Dict[str, np.ndarray]:
        self._validate()
        n = self.plan.samples_per_simulation if max_rows is None else min(self.plan.samples_per_simulation, max_rows)
        sr = self.plan.sampling_rate_hz
        t = np.arange(n, dtype=float) / sr
        rng = np.random.default_rng(int(self.cfg["random_seed"]) + sim_index)

        signals = self._base_signals(t, sim_index, rng)
        fault_active = self._apply_fault(signals, t)
        cyber_active = self._apply_cyber(signals, t, rng)
        comm_active = self._apply_communication(signals, rng)
        labels = self._labels(fault_active, cyber_active, comm_active)

        return {
            "time_s": t,
            **signals,
            "fault_active": fault_active.astype(np.int8),
            "cyber_active": cyber_active.astype(np.int8),
            "communication_active": comm_active.astype(np.int8),
            "primary_label": labels,
        }

    def preview(self, rows: int = 4000) -> Dict[str, np.ndarray]:
        rows = max(100, min(int(rows), 10_000))
        return self.generate_simulation(0, max_rows=rows)

    def iter_chunks(self, chunk_size: int = 20_000) -> Generator[Tuple[int, Dict[str, np.ndarray]], None, None]:
        """Yield chunks across one or more synthetic simulation runs.

        Returns (global_start_row, chunk_dict). This keeps memory bounded for
        large Excel exports.
        """
        self._validate()
        remaining = self.plan.requested_rows
        global_start = 0
        sim_index = 0

        while remaining > 0:
            sim_rows = min(self.plan.samples_per_simulation, remaining)
            full = self.generate_simulation(sim_index, max_rows=sim_rows)
            offset = 0
            while offset < sim_rows:
                take = min(chunk_size, sim_rows - offset)
                chunk = {k: v[offset:offset + take] for k, v in full.items()}
                chunk["simulation_id"] = np.full(take, f"SIM_{sim_index + 1:06d}", dtype=object)
                yield global_start + offset, chunk
                offset += take
            global_start += sim_rows
            remaining -= sim_rows
            sim_index += 1

    def row_tuple(self, global_row: int, chunk: Dict[str, np.ndarray], i: int) -> tuple:
        c = self.cfg
        values = {
            "row_id": global_row + 1,
            "simulation_id": chunk["simulation_id"][i],
            "time_s": chunk["time_s"][i],
            "Va": chunk["Va"][i], "Vb": chunk["Vb"][i], "Vc": chunk["Vc"][i],
            "Ia": chunk["Ia"][i], "Ib": chunk["Ib"][i], "Ic": chunk["Ic"][i],
            "Vdc": chunk["Vdc"][i], "Idc": chunk["Idc"][i],
            "P": chunk["P"][i], "Q": chunk["Q"][i], "Frequency": chunk["Frequency"][i],
            "load_pct": c["load_pct"], "power_factor": c["power_factor"], "grid_strength": c["grid_strength"],
            "fault_active": int(chunk["fault_active"][i]),
            "fault_type": c["fault_type"] if c["fault_enabled"] else "None",
            "fault_location": c["fault_location"] if c["fault_enabled"] else "None",
            "fault_resistance_ohm": c["fault_resistance_ohm"] if c["fault_enabled"] else "",
            "cyber_active": int(chunk["cyber_active"][i]),
            "cyber_type": c["cyber_type"] if c["cyber_enabled"] else "None",
            "cyber_target": c["cyber_target"] if c["cyber_enabled"] else "None",
            "cyber_magnitude_pct": c["cyber_magnitude_pct"] if c["cyber_enabled"] else "",
            "communication_active": int(chunk["communication_active"][i]),
            "primary_label": chunk["primary_label"][i],
        }
        return tuple(values[col] for col in DATA_COLUMNS)
