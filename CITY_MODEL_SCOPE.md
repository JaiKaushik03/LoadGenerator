# Lunar city synthetic data model

Source: supplied NASA_Draft V11-SM, technical concept, Tasks 1–5, Figures 1–2 and Table 4. This document is a requirements source, not proof that its proposed systems have already been built or validated. Keep the supplied proposal private; it is not included in public project assets.

## Engineering contract

Build a Python-native synthetic-data generator using editable assumptions, with separate mission-energy and fast electrical time scales. Preserve the existing explicit-PWM battery subsystem. Do not claim measured lunar performance, MATLAB equivalence, 99% physical accuracy, NASA endorsement or CHIL validation from simulation alone.

Every run must identify configuration, units, seed, model revision, parameter provenance, fidelity mode, solver steps, output intervals, events and numerical diagnostics. Scenario inputs may change outcomes; results must not be silently edited to hit a desired answer.

## Proposal traceability

| Source | Required model or behavior | Verification requirement |
|---|---|---|
| Fig 2 | MG0 power hub; MG1 habitat; MG2 ISRU; MG3 science; MG4 mobility; MG5 communications; MG6 emergency | Editable topology and asset counts; city total equals sum of nodes without double counting transfers |
| Tasks 1.1–1.2 | Solar and bidirectional DC/DC source/storage converters, local DC buses | Conservation; current/power limits; loss maps; transient step convergence |
| Task 1.3 | Grid-forming DC/AC interfaces, VSG and dVOC | AC voltage/frequency, RoCoF, synchronization and stability reference cases; do not label an energy-only efficiency model as grid-forming dynamics |
| Task 2.1 | Secondary restoration and sharing | Step-response and communication-fallback cases |
| Tasks 2.2–2.3 | Batteries, regenerative fuel cells, flywheels, supercapacitors and thermal storage | Resource-specific states and units; dispatch limits, self discharge, conversion losses and depletion; thermal energy must not be added to electric energy without a conversion device |
| Task 2.3 | Habitat/life support, ISRU, avionics, science, communication and mobility loads | Per-load AC/DC demand, schedules and priority; critical energy not served |
| Tasks 3.1–3.3 | Delay, jitter, loss, bandwidth, queues, routing, failover, holdover and partition | Seeded network scenarios; packet timestamps; local electrical control independent of network availability |
| Tasks 4.1–4.4 | DER loss, eclipse, degradation, electrical faults, false telemetry, DoS and MITM scenarios | Logged injected ground truth separate from corrupted observations; independent safety checks and deterministic fallback |
| Tasks 5.1–5.2 | MATLAB/Simulink, EXata and Typhoon/physical CHIL integration | Future adapters and actual lab comparison; no hardware-validation claim without experiments |
| Task 5.3, Table 4 | Static, reactive, forecast-only and unverified baselines; ablations and repeated seeds | Paired scenarios and confidence intervals; proposal targets are targets, never prefilled achievements |

## Numerical modes

Mission mode integrates energy and slow resource states over days/months, using controllable steps and separate output sampling. Electrical mode resolves circuit/control dynamics over selected short windows, with steps based on the fastest relevant time constant and PWM frequency. A multirate bridge must transfer initial states, setpoints and averaged losses; a long-horizon trace is not a switched-waveform trace. Record any one-way coupling until a validated two-way bridge exists.

The original 1500 V battery bench must remain an explicit profile; the proposal's representative 120 VDC asset interfaces and NASA's studied 3 kVAC transmission interfaces belong to separately selected profiles, with transformers/converters where required. Do not silently connect mismatched buses.

## Acceptance gates

1. Schema validation rejects nonfinite inputs, incompatible units, invalid topology and unsupported settings rather than ignoring them.
2. Analytic charge/discharge and circuit benchmarks; timestep-refinement studies; energy accounting including cable, converter, storage and dump losses.
3. Individual battery packs derive nominal energy from series/parallel cell counts. Cell-level trajectories require an actual cell model and mismatch parameters; pack averages must be labeled as averages.
4. Resource-specific models and parameters reviewed by the lab lead; calibrated parameter imports remain separate from defaults.
5. Chunked, bounded-memory output with CSV/JSONL and split-sheet XLSX; preflight estimates and explicit precision/aggregation metadata.
6. Fault boundary tests, reproducibility and restart tests; performance measurements from actual completed runs.
7. Independent reference comparison with agreed metrics before any accuracy percentage. "99%" requires defining which variable, operating envelope, error normalization and reference truth.

## Parameter provenance

Default ratings, efficiencies, schedules, irradiance, temperatures and degradation rates are illustrative assumptions until supported by component data or experiments. Lunar illumination requires location/terrain geometry or an explicitly supplied profile; a generic sinusoid is a scenario approximation. Regenerative fuel cells require electrolysis/fuel-cell efficiency and reactant inventory; flywheels require inertia/speed/loss; supercapacitors require capacitance/voltage/ESR; thermal storage requires thermal states and heat flows.

## Public reference anchors

- https://ntrs.nasa.gov/citations/20230013199 — distributed assets and UMIC interface trade study, including 3 kVAC transmission.
- https://ntrs.nasa.gov/citations/20240008802 — scalable lunar sources/loads and universal interfaces.
- https://ntrs.nasa.gov/citations/20240013588 — lunar surface power presentation.

## Status

Requirements and isolated development branch established. A city energy-accounting kernel, bounded resource-energy models, configuration example, JSONL/XLSX exports and 20 tests are implemented. A seven-node 24-hour run completed. Separate RK4 analytic benchmarks pass a 1% reference tolerance with fourth-order convergence. Existing battery solver remains available. Whole-city electrical/thermal physics, UI, multirate integration and experimental validation are not yet complete; component existence must not be confused with equal physical fidelity across components.
