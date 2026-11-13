# HyperGrid lunar city development build

This branch adds a working city-scale **energy-accounting model** and streaming datasets beside the existing battery switching simulator. It is the first implementation milestone, not the completed proposal or a validated industry digital twin. No claim of 99% physical accuracy or superiority to MATLAB is made.

## Run

Python 3.10+; standard library only. From this directory:

```powershell
python city_cli.py --config examples/city.json --output outputs/my-city-run
python city_export.py outputs/my-city-run --output outputs/my-city-run/city.xlsx
python -m unittest discover -s tests -v
```

Use a new run/output name each time: existing results are not overwritten. For the local city editor, run `python city_server.py` and open http://127.0.0.1:8012. Edit the complete configuration, run a bounded background job, and download Excel, JSONL and metadata. The editor binds only to loopback, rejects cross-origin submissions, limits job size and runs one job at a time. The old `app.py` remains the separate battery interface.

## Configuration

`examples/city.json` defines seven nodes matching the proposal's power-hub, habitat, ISRU, science, mobility, communication and emergency functions. Add/remove nodes and their source, load and storage records to choose asset counts. Update tie endpoints when changing nodes. Asset IDs must be globally unique. Unsupported parameters are rejected instead of silently ignored.

Sources have ratings, conversion efficiency and time-indexed availability. Loads have time-indexed demand and local service priority (0 is highest). Availability/demand schedules are explicit step functions, start at zero, and hold their last value; the example does **not** automatically repeat a lunar illumination cycle. Add the desired illumination/eclipse/fault intervals yourself. Source outages and tie islanding can be represented by zero availability.

Battery capacity is derived from series cells × parallel cells × nominal cell voltage × cell amp-hours. The energy model uses a pack aggregate; it does not claim to compute independent cell voltages or temperatures. Storage limits, efficiencies, reserve fractions and self-discharge are configurable. Positive terminal power discharges into the bus; negative power charges from it.

Other accepted electrical resource types have explicitly reduced-order energy states:

| `kind` | Required capacity parameters | Meaning |
|---|---|---|
| `battery` | `series_cells`, `parallel_cells`, `cell_voltage_v`, `cell_capacity_ah` | Nominal aggregate battery energy |
| `supercapacitor` | `capacitance_f`, `maximum_voltage_v` | Energy from ½CV²; no ESR/voltage-dependent current dynamics yet |
| `flywheel` | `inertia_kg_m2`, `maximum_speed_rad_s` | Energy from ½Jω²; no mechanical/speed-control dynamics yet |
| `regenerative_fuel_cell` | `hydrogen_capacity_kg`, `hydrogen_specific_energy_kwh_kg` | Hydrogen-inventory energy; no pressure, oxygen/water, electrolysis or fuel-cell polarization dynamics yet |

Each also requires the common storage fields shown in the battery example. Remove battery-only sizing fields when selecting a different type. Charge/discharge efficiencies represent lumped conversions. Thermal storage is deliberately rejected until a separate heat domain and electric-to-thermal interfaces are implemented; thermal kWh must not be added to electrical kWh as though interchangeable.

Dispatch currently uses local sources then local storage; surplus is exchanged on listed direct ties in order, subject to capacity, availability and configured fractional losses. It is deterministic and conservative, **not** an optimal dispatch, multihop power-flow, global critical-load scheduler or VSG/dVOC controller. Tie loss fractions are assumptions, not calculated cable I²R losses. Import/export totals are not additional city generation/consumption.

## Outputs

`metadata.json` identifies status, configuration, source/configuration hashes, environment, totals and limitations. `intervals.jsonl` is the full-resolution authoritative stream, with start/end times, interval duration, city totals, node records, individual assets and tie flows. Power fields end in `_kw`; interval energy/loss fields end in `_kwh`. Storage energy is recorded at the end of its interval. Runs split at schedule changes instead of shifting events to the next output step.

XLSX export includes metadata, city, node, asset and tie sheets. It streams XML and splits sheets at Excel's row limit without downsampling; different asset types have blank cells for inapplicable fields. Long text exceeding the Excel cell limit is rejected rather than silently truncated. JSONL remains the source of truth. Large configurations may require partitioned datasets; the present solver rejects more than ten million nominal steps. This is a resource guard, not a benchmarked capacity claim. Solver step and output interval are currently the same in energy mode, with extra event boundaries; independent output sampling remains to be added.

## Measured development checks

City, numerical and export tests pass, including cell sizing, closed-form charge/discharge, reserve/ceiling behavior, self-discharge, city/node conservation, tie capacity/loss, islanding, priority shedding, exact schedule boundaries, reproducibility, unsupported fields and split-sheet export.

The initial example completed 1,440 one-minute intervals over 24 hours, exporting 1,440 city, 10,080 node, 40,320 asset and 8,640 tie records. Maximum absolute bus-balance residual was 5.684341886080802e-14 kW. It served about 2,951.60 kWh and left about 2,088.40 kWh unmet under its assumed solar/storage sizes. These are illustrative scenario results, not lunar measurements or an adequate city design.

`docs/city/reference_results.json` records RK4 agreement against four independent closed-form cases (RC step, RL step, linearized swing-speed response and first-order thermal response), with three step sizes per case and observed convergence order around four. All satisfy a 1% relative reference-error criterion. These validate the **numerical integration primitive on those equations**, not the entire city, original switching battery solver, or an implemented grid-forming/thermal subsystem. RK4 is not yet coupled to the energy-accounting engine.

## Remaining implementation

The proposal-wide requirements and acceptance gates are in `CITY_MODEL_SCOPE.md`. Main unfinished areas are calibrated/dynamic resource models, heat networks, solar/environment models, AC/DC electrical-network and inverter control dynamics, cell mismatch/dynamics, independent output sampling, two-way multirate coupling, secondary control, communications/cyber disturbance models, verified supervisory actions, advanced configuration forms, and lab/reference integrations. No HIL deployment or actual MATLAB comparison has been performed.

The supplied proposal is retained outside this repository. The city implementation is included in the GitHub release; the supplied proposal itself is excluded. Existing project attribution remains intact.
