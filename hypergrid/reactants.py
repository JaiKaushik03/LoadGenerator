"""Closed-reactant inventory extension of the RFC energy model.

No polarization, gas-pressure or compressor dynamics are implied. Conversion
efficiencies are explicitly supplied on a consistent specific-energy basis.
"""

from .energy import Storage, finite

OXYGEN_PER_HYDROGEN = 31.9988 / (2 * 2.01588)
WATER_PER_HYDROGEN = 1 + OXYGEN_PER_HYDROGEN


class RegenerativeFuelCell(Storage):
    def __init__(self, *args, specific_energy_kwh_kg, oxygen_kg, water_kg, **kwargs):
        super().__init__(*args, **kwargs)
        self.specific_energy = finite(
            "specific_energy_kwh_kg", specific_energy_kwh_kg, 1e-12
        )
        self.oxygen_kg = finite("oxygen_kg", oxygen_kg)
        self.water_kg = finite("water_kg", water_kg)

    def step(self, requested_kw, dt_s):
        finite("dt_s", dt_s, 1e-12)
        h = dt_s / 3600
        old_charge, old_discharge = self.charge_limit_kw, self.discharge_limit_kw
        mass_before = (
            self.energy_kwh / self.specific_energy + self.oxygen_kg + self.water_kg
        )
        initial_hydrogen = self.energy_kwh / self.specific_energy
        self.discharge_limit_kw = min(
            old_discharge,
            self.oxygen_kg
            / OXYGEN_PER_HYDROGEN
            * self.specific_energy
            * self.discharge_efficiency
            / h,
        )
        self.charge_limit_kw = min(
            old_charge,
            self.water_kg
            / WATER_PER_HYDROGEN
            * self.specific_energy
            / (self.charge_efficiency * h),
        )
        try:
            result = super().step(requested_kw, dt_s)
        finally:
            self.charge_limit_kw, self.discharge_limit_kw = old_charge, old_discharge
        p = result["power_kw"]
        reacted_h2 = (
            p * h / (self.discharge_efficiency * self.specific_energy)
            if p >= 0
            else p * h * self.charge_efficiency / self.specific_energy
        )
        self.oxygen_kg = max(0.0, self.oxygen_kg - reacted_h2 * OXYGEN_PER_HYDROGEN)
        self.water_kg = max(0.0, self.water_kg + reacted_h2 * WATER_PER_HYDROGEN)
        hydrogen = self.energy_kwh / self.specific_energy
        leaked = max(0.0, initial_hydrogen - hydrogen - reacted_h2)
        result.update(
            hydrogen_kg=hydrogen,
            oxygen_kg=self.oxygen_kg,
            water_kg=self.water_kg,
            leaked_hydrogen_kg=leaked,
            mass_balance_residual_kg=mass_before
            - hydrogen
            - self.oxygen_kg
            - self.water_kg
            - leaked,
        )
        return result
