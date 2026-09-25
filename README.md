# HyperGrid Battery Digital Twin v0.2 PORTABLE

HyperGrid is a standalone battery-to-local-DC-bus simulation project intended to grow into a configurable multi-microgrid data-generation platform.

## What changed in v0.2

This build is **fully portable at the Python-package level**. The previous v0.1 launcher attempted to download FastAPI, NumPy, Numba, Pydantic and XlsxWriter from PyPI. If DNS or internet access failed, the application could not start.

v0.2 removes that failure mode. It uses only the Python 3 standard library:

- no `pip install`
- no FastAPI
- no NumPy
- no Numba
- no Pydantic
- no XlsxWriter
- no MATLAB / Simulink dependency

The browser UI, simulation API, explicit PWM solver and `.xlsx` export are all included in the ZIP.

## Run on Windows

1. Extract the ZIP completely.
2. Double-click `START_HYPERGRID_WINDOWS.bat`.
3. The program starts a local server and opens `http://127.0.0.1:8000`.

Python 3.10+ is required. The user's current Python 3.13 installation is supported by this portable build.

## Current modeled subsystem

Architecture A is used: each battery owns an independent converter path into a common local DC bus.

`Battery 2-RC ECM -> cable/contactors/fuse -> explicit switching bidirectional converter -> DC-link capacitor -> local 1500 V DC bus -> constant-power load`

Current battery features include:

- real HiTHIUM 314 Ah LFP static catalog data
- configurable number of batteries
- selectable cell-architecture or direct-pack sizing
- SOC-dependent OCV lookup and slow charge/discharge hysteresis
- 2-RC polarization dynamics
- temperature- and SOC-dependent internal resistance
- SOH / throughput aging state
- lumped battery thermal state
- selectable cable material, dimensions, temperature, geometry, contactor and fuse resistance
- geometry-derived cable inductance
- explicit PWM switch state and dead time
- selectable IGBT / SiC / ideal semiconductor catalog models
- datasheet-scaled switching loss and conduction loss
- junction thermal state
- DC-bus voltage, fixed-power and fixed-current control modes
- equal, rated-power, SOC-weighted and custom sharing
- current, SOC, battery-temperature, semiconductor-temperature, bus-OV and bus-UV protections
- Excel output containing configuration, derived values, system time series, individual battery signals and source URLs

## Fidelity settings

The converter is not replaced with an averaged duty-cycle source. HyperGrid resolves PWM states directly.

For the portable pure-Python solver, the number of integration points per switching period is:

- Preview: 10
- High: 25
- Research: 50
- Extreme: 100

With the default 2 kHz switching frequency, Extreme uses a 5 microsecond electrical integration step.

Numerical resolution does not substitute for experimental calibration. R1/R2/time-constant values remain explicit engineering seed values until HPPC/EIS data are supplied and identified.

## Main files

- `app.py` — local HTTP server and application entry point
- `hypergrid/config.py` — complete default configuration and validation
- `hypergrid/simulator.py` — battery, cable, switching converter, controls, thermal and protection algorithms
- `hypergrid/exporter.py` — native `.xlsx` writer with no external library
- `data/battery_catalog.json` — cell catalog and provenance-aware ECM seeds
- `data/semiconductor_catalog.json` — IGBT / SiC / ideal device data
- `data/sources.json` — source URLs
- `static/` — frontend
- `outputs/` — generated Excel files

## Collaboration

Use a private GitHub repository as the source of truth. Both partners clone the same repository and work in branches. See `COLLABORATION.md`.

Do not use Google Colab as the sole copy of this multi-file project; Colab runtimes are temporary. Colab can still clone the GitHub repo later for experiments or dataset generation.

## Scientific limitation that is intentionally visible

The public HiTHIUM sheet provides static electrical specifications but does not provide a complete cell-specific HPPC/EIS parameter map across SOC and temperature. HyperGrid therefore labels the current dynamic ECM values as calibration seeds. The next research-grade step is an HPPC parameter-identification/import module so measured data can replace those seeds.
