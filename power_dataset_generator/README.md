# Power-System Dataset Generator — Synthetic Prototype

This is a working desktop prototype for the dataset-generation algorithm described in the project report.

## What it currently does

- **Normal mode**: locks all factors to the baseline configuration in `config.py`.
- **Custom mode**: starts from the same baseline and lets the researcher change operating, fault, cyberattack, communication, and sampling factors.
- **Preview**: creates a small synthetic waveform preview before a large export.
- **Generate Excel Dataset**: asks where to save and creates a new `.xlsx` workbook.
- **Up to 1,000,000 data rows** per workbook in this prototype.
- Excel output includes:
  - `Dataset`
  - `Configuration`
  - `Metadata`
  - `Data_Dictionary`
  - `Summary`
- Uses streaming/chunked Excel writing so the full dataset is not held in RAM.
- If the selected filename already exists, the exporter automatically creates a unique filename instead of overwriting it.

## IMPORTANT — research-use limitation

The current `SyntheticPowerSystemGenerator` is **not a validated power-system simulator**. It generates transparent, physically-inspired demo signals so the GUI, parameter controls, labeling, and dataset pipeline can be developed and demonstrated now.

Before using the data as research-grade physical results:

1. Replace the demo baseline values in `config.py` with professor/lab-approved values.
2. Replace the synthetic generator layer with the real MATLAB/Simulink/PSCAD (or other) simulation output.
3. Keep the same GUI, metadata, labeling, chunked export, and dataset structure.

This separation is intentional: the application/data pipeline is independent from the electrical simulator.

## Install and run on Windows

### Easiest

Double-click:

`install_and_run.bat`

It installs the Python packages and launches the app.

### Or manually

```bash
python -m pip install -r requirements.txt
python app.py
```

Tkinter normally ships with standard Windows Python installations.

## Normal mode

Normal mode uses the current baseline configuration and disables editing. Only the requested row count remains editable.

The values currently present are **demo defaults**, not validated laboratory values.

## Custom mode

Custom mode unlocks the parameter tabs:

- Operating
- Fault
- Cyber
- Communication
- Sampling

Every field starts at the same normal baseline. Changed fields are marked **CUSTOM**. `Reset Custom to Normal` restores the baseline.

## Algorithm flow

```text
Load normal configuration
        |
        v
Normal or Custom?
        |
        +-- Normal -> keep baseline
        |
        +-- Custom -> replace user-edited factors
        |
        v
Generate synthetic simulation run
        |
        v
Apply fault if enabled
        |
        v
Apply cyberattack if enabled
        |
        v
Apply communication impairment if enabled
        |
        v
Create labels + metadata
        |
        v
Stream rows to Excel
        |
        v
Repeat simulation runs until requested row count is reached
```

## How row count works

A single synthetic run contains:

`sampling_rate_hz × simulation_duration_s`

rows.

Example:

- sampling rate = 1,000 Hz
- duration = 10 s
- rows per run = 10,000
- requested rows = 1,000,000

The program automatically generates 100 run IDs (`SIM_000001` ... `SIM_000100`) and stops exactly at 1,000,000 rows.

## Current synthetic fault behavior

The fault layer uses:

- fault type
- fault location
- fault resistance
- start time
- duration

Lower fault resistance produces a stronger synthetic voltage sag/current rise. This relationship is only a demo behavior until connected to the actual power-system model.

## Current cyberattack types

- Bias
- Scaling
- Ramp
- Noise
- Stuck-at
- Replay
- Spike
- Intermittent

Targets can include:

`Va, Vb, Vc, Ia, Ib, Ic, Vdc, Idc, P, Q, Frequency`

## Next research-development step

The next important step is **simulator integration**. Build an adapter with the same responsibility as `SyntheticPowerSystemGenerator`, but instead of constructing signals mathematically, it should:

1. send the selected GUI parameters to the electrical model;
2. run the simulation;
3. retrieve synchronized measurements;
4. return them to the existing labeling/export pipeline.

That lets the UI and algorithm stay the same while the data source becomes physically validated.
