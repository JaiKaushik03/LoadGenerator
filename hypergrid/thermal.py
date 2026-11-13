"""Exact constant-input lumped sensible-heat tank with independent heat units."""

from dataclasses import dataclass
import math
from .energy import finite


@dataclass
class ThermalTank:
    mass_kg: float
    specific_heat_j_kg_k: float
    temperature_c: float
    ambient_c: float
    conductance_w_k: float
    min_temperature_c: float
    max_temperature_c: float

    def __post_init__(self):
        finite("mass_kg", self.mass_kg, 1e-9)
        finite("specific_heat_j_kg_k", self.specific_heat_j_kg_k, 1e-9)
        finite("conductance_w_k", self.conductance_w_k)
        for key in [
            "temperature_c",
            "ambient_c",
            "min_temperature_c",
            "max_temperature_c",
        ]:
            finite(key, getattr(self, key), -273.15)
        if not self.min_temperature_c < self.max_temperature_c:
            raise ValueError("Invalid thermal temperature range")

    def step(self, input_kw_th, demand_kw_th, dt_s):
        finite("input_kw_th", input_kw_th)
        finite("demand_kw_th", demand_kw_th)
        finite("dt_s", dt_s, 1e-12)
        capacity = self.mass_kg * self.specific_heat_j_kg_k
        finite("thermal_capacity_j_k", capacity, 1e-12)
        initial = self.temperature_c
        if self.conductance_w_k:
            decay = math.exp(-self.conductance_w_k * dt_s / capacity)
            gain = (
                -math.expm1(-self.conductance_w_k * dt_s / capacity)
                / self.conductance_w_k
            )
            passive_end = self.ambient_c + (initial - self.ambient_c) * decay
        else:
            gain = dt_s / capacity
            passive_end = initial
        unconstrained_end = passive_end + input_kw_th * 1000 * gain
        served = min(
            demand_kw_th,
            max(0.0, (unconstrained_end - self.min_temperature_c) / (1000 * gain)),
        )
        end = unconstrained_end - served * 1000 * gain
        # Bypass only incoming heater heat; a hot boundary cannot be countered
        # by an invented unlimited cooler. Overtemperature remains observable.
        dump_kw = min(
            input_kw_th, max(0.0, (end - self.max_temperature_c) / (1000 * gain))
        )
        self.temperature_c = end - dump_kw * 1000 * gain
        delta = capacity * (self.temperature_c - initial) / 3_600_000
        h = dt_s / 3600
        if self.conductance_w_k:
            net_w = (input_kw_th - served - dump_kw) * 1000
            equilibrium = self.ambient_c + net_w / self.conductance_w_k
            integral = (equilibrium - self.ambient_c) * dt_s + (
                initial - equilibrium
            ) * gain * capacity
            ambient_loss = self.conductance_w_k * integral / 3_600_000
        else:
            ambient_loss = 0.0
        return {
            "temperature_c": self.temperature_c,
            "overtemperature": self.temperature_c > self.max_temperature_c + 1e-9,
            "input_kw_th": input_kw_th,
            "served_kw_th": served,
            "unserved_kw_th": demand_kw_th - served,
            "dump_kw_th": dump_kw,
            "ambient_loss_kwh_th": ambient_loss,
            "stored_change_kwh_th": delta,
            "balance_residual_kwh_th": (input_kw_th - served - dump_kw) * h
            - delta
            - ambient_loss,
        }
