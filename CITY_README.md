# HyperGrid lunar-city model guide

HyperGrid is configurable research software for generating synthetic resource and electrical datasets. Its seven-node preset covers a power hub, habitat, ISRU, science, mobility, communications and emergency services. Node count, source count, storage architecture, demands, links, schedules and solver settings are editable. Defaults are illustrative engineering assumptions, not measured lunar specifications.

## Choose the appropriate model

| Mode | State and time scale | Purpose and boundary |
|---|---|---|
| Mission | Aggregate resource energy; event-aligned seconds/minutes or other selected steps | Long resource horizons; deterministic local dispatch and ordered direct energy exchanges. No AC load-flow or optimizer. |
| Electrical RL | Balanced alpha-beta source RL, bus capacitance, cable RL; microsecond integration | Primary droop, VSM and dVOC controls; three-phase waveforms and energy diagnostics. |
| Electrical LCL | Inverter-side L/R, filter C, grid-side L/R, bus C; cascaded dq PI states | Averaged inverter, feedforward, decoupling, reference-current limiting and antiwindup. |
| Coupled RL/LCL | Electrical microsteps inside resource macro intervals | Resource capability constrains the ideal bridge; actual integrated port energy updates storage. Refine both steps to assess coupling error. |
| Existing battery | Separate explicit PWM battery/DC-bus simulator | Original 2-RC battery switching experiment; independent of the city aggregate battery state. |

Electrical modes assume balanced three-phase circuits, resistive loads and ideal averaged lossless DC/AC conversion. They do not resolve semiconductor switching, converter hardware, nonlinear load harmonics or detailed DC/DC dynamics. The original battery PWM solver does not automatically give every city cell a switched electrochemical trajectory.

## Quick start

Python 3.10+; no package installation for application or regression tests.

```sh
python city_server.py
```

Open http://127.0.0.1:8012. Select a preset, edit JSON, and run. The dashboard shows configured nodes, output count, simulated horizon, solver runtime, power preview and diagnostics. Plot previews are explicitly sampled; downloaded JSONL is full resolution. The loopback-only editor runs one job at a time and bounds browser job sizes. Larger jobs use the CLI.

```sh
python city_cli.py --config examples/city-hybrid.json --output outputs/my-mission
python city_export.py outputs/my-mission --output outputs/my-mission/city.xlsx
python city_csv.py outputs/my-mission --output outputs/my-mission/csv
python electrical_cli.py --mode coupled --config examples/coupled-lcl.json --output outputs/my-coupled --xlsx
python electrical_cli.py --mode emt --config examples/lcl.json --output outputs/my-electrical --xlsx
python -m unittest discover -s tests -v
```

Use new output paths; existing datasets are preserved. Generate current presets using `python build_hybrid_example.py` and the preset factories in `electrical_cli.py`/`hypergrid.lcl`.

## Physics and configuration

Mission schema is demonstrated in `examples/city-hybrid.json`. Unsupported fields, duplicate IDs, invalid topology, nonfinite parameters, unsafe electrical steps and incompatible modes are rejected. Schedules are piecewise constant `{time_s, value}` arrays beginning at zero and holding their last value. They do not repeat automatically. Explicit illumination profiles represent eclipses or an assumed lunar day; terrain shadowing and ephemerides are not inferred.

* **Sources:** rated kW, conversion efficiency and availability. Optional single-diode PV parameters define series cells, parallel strings, photocurrent, saturation current, series/shunt resistance, ideality, temperature coefficient, bandgap, cell temperature, reference irradiance and dust transmission. MPP is solved numerically. Available array output is distinct from actual dispatched output and curtailment. Manufacturer calibration is still required for predictive physical use.
* **Battery:** capacity = series cells × parallel cells × nominal cell voltage × Ah / 1000. Configurable charge/discharge limits, efficiencies, reserve, ceiling and exponential self-discharge. Cell-count and mean-cell quantities are uniform aggregate equivalents, not independent cell measurements or mismatch simulation.
* **Regenerative fuel cell:** hydrogen energy with H2/O2/H2O inventories and stoichiometric reaction limits, charge/discharge efficiency and separately logged H2 leakage. Oxygen can limit discharge and water can limit electrolysis. Specific energy and efficiencies require a consistent heating-value basis. No gas-pressure, compressor or polarization model.
* **Flywheel:** energy 1/2 J omega², configurable inertia, maximum speed, power/efficiency limits and standby loss; derived speed is exported. No detailed rotor or bearing controller.
* **Supercapacitor:** energy 1/2 C V², configurable capacity, voltage, power/efficiency limits and standby loss; derived voltage is exported. No ESR or individual-cell balancing dynamics.
* **Thermal tank:** fixed-mass sensible heat with exact constant-input linear-conductance integration. Heater input uses only electricity actually served. COP, ambient extraction, conversion loss, reserve, bypassed incoming heat and overtemperature are explicit. Conductance is a lumped boundary parameter, not lunar atmospheric convection. A hot boundary is allowed to overheat the tank; no free cooling is invented. No nonlinear radiator or phase-change model.
* **Links:** mission capacity/availability/fractional losses; electrical resistance, inductance and optional ideal endpoint transformer ratios. Electrical line opening diverts residual inductor current into a configured snubber loop. Ratios preserve power but do not constitute a physical UMIC design.
* **Controls:** primary droop/VSM/dVOC; LCL mode adds dq voltage/current PI loops with back-calculation antiwindup. The configured current limit bounds the reference, not every instantaneous transient current. Controller frequency and bus instantaneous frequency are distinct outputs.

Mission dispatch is local generation, local storage, then listed direct ties in order. It is not optimal scheduling or multihop routing. Positive storage terminal power discharges; negative charges. Resources cannot supply energy they do not hold. Coupled mode uses electrical lines as its sole network and therefore requires empty mission `ties`, matching node IDs and matching horizons. Coupled telemetry is currently rejected explicitly.

## Telemetry and fault scenarios

Mission telemetry uses a reproducible seed for delay, jitter, packet loss and measurement noise. Bias, replay and drop intervals alter observations while retaining physical truth. Ground-truth attack labels are evaluation labels; using them as detector features would leak the target. Queue/history bounds protect long runs. A finite-power/freshness verification helper rejects unsafe dispatch proposals; it is not an autonomous agent integration. This is not EXata, an SDN emulator or a trained intrusion detector. Electrical topology schedules and source enable/capability settings provide separately modeled circuit disturbances.

## Data contract, horizons and recovery

`intervals.jsonl` is authoritative. Mission records contain interval boundaries, city totals, nodes, assets and ties; electrical/coupled modes have explicitly different schemas. kW/kWh are mission electrical units, W/J are fast electrical units, and `_th` denotes heat. Never sum heat into electrical totals. Aggregated output powers are time-weighted means; interval energy increments are summed; state and measurement fields are end-of-output-interval values. `output_interval_s` may be coarser than `step_s` but cannot claim finer integration resolution. Event boundaries are integrated even inside coarse output intervals.

Duration and intervals are configurable; there is no benchmarked universal maximum number of years. Memory, disk, stiffness and requested rows determine practical limits. The mission solver guards at ten million nominal integration steps; the browser uses a much lower bound. Estimate samples as ceil(duration/output_interval), then multiply by per-sample node/asset/link counts for table rows. One million table rows is not one million distinct time samples.

Mission CLI checkpoints commit JSON model state, deterministic RNG/queue state, totals, output offset and SHA-256 prefix. `--resume` verifies exact source/configuration fingerprints and the committed prefix, preserves any uncommitted tail in an audit file, then replays it. An OS lock prevents concurrent writers. Byte-identical recovery is tested on the same environment; do not assume cross-platform floating-point identity. Checkpoints are JSON, not executable pickle.

Metadata records configuration, source/config hashes, environment, status, scoped limitations, totals and dataset SHA-256. Both exporters reject incomplete runs or altered checksummed streams. XLSX uses literal strings, bounded-memory table spooling, flattened metadata and worksheet splitting at Excel's row limit without downsampling. CSV escapes formula-like text, retains numeric negatives, and includes per-table hashes/counts and source metadata. Export staging requires additional disk space proportional to output; no format removes that cost.

## Validation and reproducible evidence

```sh
python -m venv .venv-validation
# Activate that environment, then:
python -m pip install -r requirements-validation.txt
python validate_references.py --output outputs/my-reference-results.json
python benchmarks/city_release.py --output outputs/my-release-benchmark
```

The optional comparison uses pvlib's Lambert-W single-diode solver for 12 irradiance/temperature cases, and SciPy DOP853 for droop/VSM/dVOC RL and LCL trajectories. It records configurations, versions, source fingerprints and voltage/current waveform errors. The acceptance criterion is <=1% on those defined comparisons. Sharing equations/inputs while changing numerical solver checks implementation agreement, not independent physical calibration.

Regression tests also cover analytic RC/RL/swing/thermal convergence, resource/reactant conservation, passive network energy, transformer scaling, finite source power, islanding dissipation, thermal served-electricity coupling, output aggregation, invalid inputs, restart replay, queue recovery and independent XLSX XML integrity. CI executes tests across Python versions, model smoke runs and optional references. See [scope/evidence matrix](CITY_MODEL_SCOPE.md) and the committed reference/benchmark JSON files for measured results.

## Engineering references

* [NASA modular AC/DC interface study](https://ntrs.nasa.gov/citations/20230013309): 120 VDC assets and 3 kVAC transmission context; hardware is not reproduced here.
* [NASA lunar microgrid trade study](https://ntrs.nasa.gov/citations/20230013199): scalable lunar power sharing context.
* [Sandia/NIST single-diode model](https://pvpmc.sandia.gov/modeling-guide/2-dc-module-iv/single-diode-equivalent-circuit-models/): PV equivalent circuit.
* [NREL grid-forming inverter model paper](https://johnsonlab.ece.utexas.edu/wp-content/uploads/2024/08/88117.pdf): primary controllers and cascaded-control/LCL modeling context.
* [SciPy solve_ivp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html) and [pvlib single-diode reference](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.singlediode.html): optional numerical comparators.
* [NASA regenerative fuel-cell testing](https://www.nasa.gov/general/nasa-regenerative-fuel-cell-testing/): technology context, not calibration data for these defaults.

Physical validation, detailed converter/cell calibration, nonlinear thermal radiation, full communications/control integration and HIL experiments remain separate research work. No NASA endorsement, funding, certified accuracy, MATLAB superiority or flight suitability is asserted.
