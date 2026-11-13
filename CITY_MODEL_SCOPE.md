# Requirements and evidence matrix

This tracks implemented synthetic-data software separately from physical validation. The private proposal is not distributed. Seven functional node roles are a configurable example, not a fixed city design.

| Requirement | Implemented artifact | Verification / boundary |
|---|---|---|
| Whole city, selectable asset counts | `hypergrid/city.py`, hybrid preset | Seven-node integration, unique IDs/topology rejection; arrays support different counts. No city-sizing optimizer. |
| Battery pack and cell-level context | `energy.py`, original `simulator.py` | Pack sizing/reserve/conservation tests. City cell values are aggregate means. Original PWM engine remains separate. |
| Solar sources | `solar.py` | KCL/MPP/scaling/darkness tests; 12 pvlib reference cases. Assumed cell parameters, no illumination ephemeris. |
| H2/O2/H2O cycle | `reactants.py` | Oxygen/water-limited reactions, closed-cycle mass conservation, leakage tests. No pressure/polarization. |
| Flywheel / supercap | `energy.py`, city output | Energy-speed/voltage capacity tests; lumped standby/conversion losses. |
| Thermal energy and actual heater supply | `thermal.py`, `city.py`, `coupled.py` | Analytic response, exact subdivision, starvation, overtemperature, energy residuals. Linear-conductance sensible-heat tank. |
| Converter / grid-forming dynamics | `emt.py`, `lcl.py` | Droop/VSM/dVOC, RL/LCL, cascaded dq PI, finite DC modulation/power envelope. Independent DOP853 comparisons. Averaged ideal bridge, not UMIC/switch hardware. |
| City-wide electrical interconnections | Electrical line model | R/L losses, stored energy, ideal transformer referral, opening/snubber conservation tests. Balanced network only. |
| Mission and electrical time scales | `coupled.py`, `city.py` | Actual integrated port energy updates resources; empty stores cannot power loads; output aggregation preserves energy. Macro coupling requires refinement. |
| Reproducible communication disturbances | `telemetry.py` | Delay/jitter/drop/noise/bias/replay, queue/RNG recovery, truth preserved. Mission-only; no SDN/EXata or trained IDS. |
| Action verification / local control | `verify_dispatch`, primary controllers | Finite envelope/freshness rejection and local primary dynamics. No trained-agent policy or end-to-end safety certification. |
| Dataset generation and extraction | CLI, JSONL, XLSX, CSV | Source/config/data hashes; worksheet split, formula text, corrupted export rejection; no downsampling in full outputs. |
| Recoverable long jobs | `checkpoints.py`, mission CLI | Locked writer, verified committed prefix, preserved tail, byte-identical same-environment recovery tests. Electrical restart not implemented. |
| Usable evidence | Browser dashboard, tests, optional comparisons, benchmark runner | Real local browser verification; CI and committed measurement reports. No claim that numerical agreement establishes full physical accuracy. |
| Lab / MATLAB / Typhoon / EXata comparison | Not integrated | Requires independent configured reference or lab data. No external-tool equivalence claimed. |
| Validated lunar digital twin | Not established | Requires calibrated specs, loads, illumination, measured dynamics and uncertainty bounds. |

See [model guide](CITY_README.md) for commands, units, assumptions and references. Numerical reference acceptance is <=1% for explicitly stated cases. It is not a blanket '99% accurate city' claim.
