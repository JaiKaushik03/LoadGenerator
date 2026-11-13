"""Uniform-illumination, single-diode PV with explicit cell-level parameters.

Equation reference: Sandia PVPMC single-diode equivalent circuit. Parameter
temperature scaling is explicitly modeled; no manufacturer calibration implied.
"""

from dataclasses import dataclass
from functools import lru_cache
import math
from .energy import finite

K_B = 1.380649e-23
Q_E = 1.602176634e-19


@dataclass(frozen=True)
class SolarArray:
    series_cells: int
    parallel_strings: int
    photocurrent_ref_a: float
    saturation_current_ref_a: float
    series_resistance_cell_ohm: float
    shunt_resistance_cell_ohm: float
    ideality_factor: float
    current_temp_coefficient_a_k: float
    bandgap_ev: float
    cell_temperature_c: float = 25.0

    def __post_init__(self):
        for key in ["series_cells", "parallel_strings"]:
            x = getattr(self, key)
            if isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= 100000:
                raise ValueError(key + " must be a positive integer <=100000")
        finite("photocurrent_ref_a", self.photocurrent_ref_a, 1e-9, 10000.0)
        finite("saturation_current_ref_a", self.saturation_current_ref_a, 1e-30, 1.0)
        finite(
            "series_resistance_cell_ohm", self.series_resistance_cell_ohm, 0.0, 10000.0
        )
        finite("shunt_resistance_cell_ohm", self.shunt_resistance_cell_ohm, 1e-9, 1e15)
        finite("ideality_factor", self.ideality_factor, 0.5, 5.0)
        finite(
            "current_temp_coefficient_a_k",
            self.current_temp_coefficient_a_k,
            -100.0,
            100.0,
        )
        finite("bandgap_ev", self.bandgap_ev, 0.1, 5.0)
        finite("cell_temperature_c", self.cell_temperature_c, -100.0, 150.0)

    def parameters(self, irradiance_w_m2, temperature_c):
        finite("irradiance_w_m2", irradiance_w_m2, 0.0, 5000.0)
        finite("temperature_c", temperature_c, -100.0, 150.0)
        temp = temperature_c + 273.15
        ref = 298.15
        iph = (
            max(
                0.0,
                self.photocurrent_ref_a
                + self.current_temp_coefficient_a_k * (temp - ref),
            )
            * irradiance_w_m2
            / 1000.0
        )
        i0 = (
            self.saturation_current_ref_a
            * (temp / ref) ** 3
            * math.exp(
                self.bandgap_ev
                * Q_E
                / (self.ideality_factor * K_B)
                * (1 / ref - 1 / temp)
            )
        )
        return iph, i0, self.ideality_factor * K_B * temp / Q_E

    def cell_current(self, voltage_v, irradiance_w_m2=1000.0, temperature_c=25.0):
        finite("cell_voltage_v", voltage_v)
        iph, i0, a = self.parameters(irradiance_w_m2, temperature_c)
        rs, rsh = self.series_resistance_cell_ohm, self.shunt_resistance_cell_ohm

        def residual(current):
            x = voltage_v + current * rs
            return iph - i0 * math.expm1(min(700.0, x / a)) - x / rsh - current

        if residual(0.0) <= 0:
            return 0.0
        lo, hi = 0.0, iph
        for _ in range(64):
            mid = (lo + hi) / 2
            if residual(mid) > 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    @lru_cache(maxsize=4096)
    def operating_point(
        self, irradiance_w_m2, temperature_c=None, dust_transmission=1.0
    ):
        finite("dust_transmission", dust_transmission, 0.0, 1.0)
        finite("irradiance_w_m2", irradiance_w_m2, 0.0, 5000.0)
        temperature_c = (
            self.cell_temperature_c if temperature_c is None else temperature_c
        )
        irradiance = irradiance_w_m2 * dust_transmission
        iph, i0, a = self.parameters(irradiance, temperature_c)
        if iph == 0:
            return {
                "array_voltage_v": 0.0,
                "array_current_a": 0.0,
                "array_power_kw": 0.0,
                "cell_voc_v": 0.0,
                "cell_temperature_c": temperature_c,
                "effective_irradiance_w_m2": irradiance,
            }
        lo, hi = 0.0, a * math.log1p(iph / i0)
        for _ in range(64):
            v = (lo + hi) / 2
            if iph - i0 * math.expm1(v / a) - v / self.shunt_resistance_cell_ohm > 0:
                lo = v
            else:
                hi = v
        voc = (lo + hi) / 2
        left, right = 0.0, voc
        golden = (math.sqrt(5) - 1) / 2
        x = right - golden * (right - left)
        y = left + golden * (right - left)

        def power(v):
            return v * self.cell_current(v, irradiance, temperature_c)

        px, py = power(x), power(y)
        for _ in range(64):
            if px > py:
                right, y, py = y, x, px
                x = right - golden * (right - left)
                px = power(x)
            else:
                left, x, px = x, y, py
                y = left + golden * (right - left)
                py = power(y)
        v = (left + right) / 2
        i = self.cell_current(v, irradiance, temperature_c)
        return {
            "array_voltage_v": v * self.series_cells,
            "array_current_a": i * self.parallel_strings,
            "array_power_kw": v
            * i
            * self.series_cells
            * self.parallel_strings
            / 1000.0,
            "cell_voc_v": voc,
            "cell_temperature_c": temperature_c,
            "effective_irradiance_w_m2": irradiance,
        }
