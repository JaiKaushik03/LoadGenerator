# Changelog

## v0.2 PORTABLE
- Removed all third-party runtime dependencies.
- Replaced FastAPI with a Python standard-library threaded local HTTP server.
- Replaced Pydantic models with a native validated configuration engine.
- Replaced NumPy/Numba solver dependency with a standalone explicit-PWM pure-Python solver.
- Replaced XlsxWriter dependency with a native OOXML `.xlsx` exporter.
- Added fail-safe Windows launcher that never attempts a network install.
- Preserved configurable multi-battery Architecture A, electrothermal 2-RC ECM, cable R-L, PWM switching, converter losses, controls, protections and Excel datasets.
- Added GitHub collaboration guidance and Git ignore rules.

## v0.1
- Initial prototype using FastAPI, NumPy, Numba, Pydantic and XlsxWriter.
