"""Configuration for the Power-System Dataset Generator prototype.

IMPORTANT:
The values below are DEMONSTRATION BASELINES for the synthetic signal generator.
They are not claimed to be validated values for any specific FIU laboratory model.
Replace them with the professor/lab-approved electrical parameters before research use.
"""

from copy import deepcopy

NORMAL_CONFIG = {
    # Dataset / simulator
    "rows": 100_000,
    "sampling_rate_hz": 1_000,
    "simulation_duration_s": 10.0,
    "random_seed": 42,
    "natural_noise_pct": 0.20,

    # Operating condition (demo baseline)
    "load_pct": 70.0,
    "power_factor": 0.95,
    "nominal_voltage_rms_v": 230.0,
    "nominal_current_rms_a": 50.0,
    "frequency_hz": 60.0,
    "vdc_v": 700.0,
    "idc_a": 25.0,
    "grid_strength": "Normal",
    "feeder_impedance_pu": 0.05,
    "inverter1_power_pct": 50.0,
    "inverter2_power_pct": 50.0,

    # Fault settings
    "fault_enabled": False,
    "fault_type": "A-G",
    "fault_location": "MG1",
    "fault_resistance_ohm": 5.0,
    "fault_start_s": 4.0,
    "fault_duration_s": 0.20,

    # Cyberattack settings
    "cyber_enabled": False,
    "cyber_type": "Bias",
    "cyber_target": "Va",
    "cyber_location": "MG1",
    "cyber_magnitude_pct": 5.0,
    "cyber_start_s": 4.0,
    "cyber_duration_s": 2.0,
    "cyber_ramp_pct_per_s": 2.0,
    "cyber_replay_delay_s": 0.25,
    "cyber_intermit_on_s": 0.20,
    "cyber_intermit_off_s": 0.30,

    # Communication settings
    "comm_enabled": False,
    "packet_loss_pct": 0.0,
    "delay_ms": 0.0,
    "jitter_ms": 0.0,
    "repeat_sample_pct": 0.0,
    "quantization_bits": 16,
}

FAULT_TYPES = [
    "A-G", "B-G", "C-G",
    "AB", "BC", "CA",
    "AB-G", "BC-G", "CA-G",
    "ABC", "ABC-G",
]

LOCATIONS = ["PCC", "MG1", "MG2", "MG3", "INV1", "INV2"]

CYBER_TYPES = [
    "Bias", "Scaling", "Ramp", "Noise", "Stuck-at",
    "Replay", "Spike", "Intermittent",
]

CYBER_TARGETS = [
    "Va", "Vb", "Vc", "Ia", "Ib", "Ic",
    "Vdc", "Idc", "P", "Q", "Frequency",
]

GRID_STRENGTHS = ["Weak", "Normal", "Strong"]

DATA_COLUMNS = [
    "row_id", "simulation_id", "time_s",
    "Va", "Vb", "Vc", "Ia", "Ib", "Ic",
    "Vdc", "Idc", "P", "Q", "Frequency",
    "load_pct", "power_factor", "grid_strength",
    "fault_active", "fault_type", "fault_location", "fault_resistance_ohm",
    "cyber_active", "cyber_type", "cyber_target", "cyber_magnitude_pct",
    "communication_active", "primary_label",
]

DATA_DICTIONARY = {
    "row_id": "Unique row number in the exported dataset.",
    "simulation_id": "Synthetic simulation/run identifier.",
    "time_s": "Time within the current simulation in seconds.",
    "Va/Vb/Vc": "Synthetic three-phase instantaneous voltages (V).",
    "Ia/Ib/Ic": "Synthetic three-phase instantaneous currents (A).",
    "Vdc": "Synthetic inverter DC-link voltage (V).",
    "Idc": "Synthetic inverter DC current (A).",
    "P": "Synthetic active power estimate (W).",
    "Q": "Synthetic reactive power estimate (var).",
    "Frequency": "Synthetic grid frequency (Hz).",
    "load_pct": "Selected load level (%).",
    "power_factor": "Selected operating power factor.",
    "grid_strength": "Selected qualitative grid-strength setting.",
    "fault_active": "1 when the configured fault is active at that time, otherwise 0.",
    "fault_type": "Configured fault type.",
    "fault_location": "Configured fault location.",
    "fault_resistance_ohm": "Configured fault resistance in ohms.",
    "cyber_active": "1 when the configured cyberattack is active at that time, otherwise 0.",
    "cyber_type": "Configured cyberattack type.",
    "cyber_target": "Measurement channel targeted by the cyberattack.",
    "cyber_magnitude_pct": "Configured attack magnitude (%).",
    "communication_active": "1 when communication impairment mode is enabled.",
    "primary_label": "Normal, Fault, Cyberattack, Combined, or Communication.",
}


def normal_config():
    return deepcopy(NORMAL_CONFIG)
