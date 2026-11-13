"""Conservative reduced-order electrical storage. Not an electrochemical solver."""

from dataclasses import dataclass
import math


def finite(name, value, minimum=0.0, maximum=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} outside [{minimum}, {maximum}]")
    return float(value)


def battery_capacity_kwh(
    series_cells, parallel_cells, cell_voltage_v, cell_capacity_ah
):
    for name, value in [
        ("series_cells", series_cells),
        ("parallel_cells", parallel_cells),
    ]:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    return (
        series_cells
        * parallel_cells
        * finite("cell_voltage_v", cell_voltage_v, 0.001)
        * finite("cell_capacity_ah", cell_capacity_ah, 0.001)
        / 1000
    )


@dataclass
class Storage:
    name: str
    capacity_kwh: float
    energy_kwh: float
    charge_limit_kw: float
    discharge_limit_kw: float
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    min_fraction: float = 0.1
    max_fraction: float = 0.95
    self_discharge_per_hour: float = 0.0

    def __post_init__(self):
        finite("capacity_kwh", self.capacity_kwh, 1e-12)
        finite("energy_kwh", self.energy_kwh, 0, self.capacity_kwh)
        for n in ["charge_limit_kw", "discharge_limit_kw", "self_discharge_per_hour"]:
            finite(n, getattr(self, n))
        for n in ["charge_efficiency", "discharge_efficiency"]:
            finite(n, getattr(self, n), 1e-12, 1)
        finite("min_fraction", self.min_fraction, 0, 1)
        finite("max_fraction", self.max_fraction, self.min_fraction, 1)
        if self.min_fraction == self.max_fraction:
            raise ValueError("Storage operating range must be nonzero")

    def step(self, requested_kw, dt_s):
        """Positive power delivers to bus; negative power charges from bus.

        Limits apply to terminal power. Self-discharge can reduce energy below
        operating reserve; reserve is a dispatch constraint, not created energy.
        """
        finite("requested_kw", requested_kw, -math.inf)
        h = finite("dt_s", dt_s, 1e-12) / 3600
        initial = self.energy_kwh
        idle_loss = initial * -math.expm1(-self.self_discharge_per_hour * h)
        self.energy_kwh -= idle_loss
        if requested_kw >= 0:
            available = max(0, self.energy_kwh - self.capacity_kwh * self.min_fraction)
            p = min(
                requested_kw,
                self.discharge_limit_kw,
                available * self.discharge_efficiency / h,
            )
            change = -p * h / self.discharge_efficiency
            conversion_loss = p * h * (1 / self.discharge_efficiency - 1)
        else:
            room = max(0, self.capacity_kwh * self.max_fraction - self.energy_kwh)
            p = -min(
                -requested_kw, self.charge_limit_kw, room / (self.charge_efficiency * h)
            )
            change = -p * h * self.charge_efficiency
            conversion_loss = -p * h * (1 - self.charge_efficiency)
        self.energy_kwh += change
        loss = idle_loss + conversion_loss
        residual = initial - self.energy_kwh - p * h - loss
        return {
            "power_kw": p,
            "energy_kwh": self.energy_kwh,
            "fraction": self.energy_kwh / self.capacity_kwh,
            "loss_kwh": loss,
            "balance_residual_kwh": residual,
        }
