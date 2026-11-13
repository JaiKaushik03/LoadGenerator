# HyperGrid research software completion plan

User-authorized scope: configurable whole-city synthetic-data software, explicit component models, slow/fast timescales, reference-equation and solver-convergence validation. Assumed parameters remain labeled; no guaranteed salary or physical-accuracy percentage. Preserve contributor attribution, original battery solver and unrelated repositories. Keep the proposal itself private.

## Acceptance sequence

1. Resource physics: implemented and verified at the reduced-order fidelity documented in CITY_README.md: battery pack architecture, hydrogen/oxygen/water cycle, flywheel speed, capacitor voltage, thermal storage and actual electricity-to-heat coupling.
2. Environmental generation: single-diode PV, series/parallel scaling, irradiance/temperature/dust inputs and explicit provenance.
3. Electrical network: parameterized AC/DC interfaces, grid-forming controls, finite source/storage capability, cable/filter dynamics, protection and short-window simulation.
4. Multirate integration: explicit state handoff, returned energy/loss accounting, independent output sampling and no hidden interpolation claims.
5. Scenario/telemetry layer: reproducible fault and communication events, corrupted observations separated from ground truth, action verification and local fallback.
6. Dataset engineering: per-component/node/city schemas, units, metadata, bounded streaming, CSV/XLSX, restart support and preflight resource estimates.
7. Usability: scenario presets, component editor, model/fidelity explanation, diagnostics and demo evidence.
8. Release evidence: analytic cases, timestep-refinement sweeps, conservation residuals, regression/negative tests, repeatability, runtime/memory measurements and a requirements-to-evidence status matrix.

Only mark an item complete after the actual implementation and its integration checks pass. A numerical reference test does not validate an entire physical subsystem. Full lab calibration, proprietary-tool parity and CHIL integration cannot be claimed without independent artifacts and experiments.

## Current software release evidence

All eight acceptance areas now have implemented artifacts and scoped verification in CITY_MODEL_SCOPE.md. The regression suite passes 77 tests locally. Optional reference comparisons pass 12 solar and six electrical controller cases. The browser completed hybrid, LCL and coupled-LCL runs and downloaded a structurally valid workbook; changing presets clears previous results. Three-repeat runtime measurements are committed in docs/city/release-benchmark.json. CI provides independent platform/version checks.

This completes a runnable, documented synthetic-data software release at the stated model fidelity. It does not complete the entire research proposal: measured component calibration, detailed individual-cell electrochemistry, semiconductor/DC converter loss/dynamics, nonlinear radiation, trained agent policies, SDN emulation, and HIL validation remain explicitly outside this release.
