# HyperGrid collaboration workflow

The project is intentionally self-contained, so every collaborator needs only Python 3.10+.

Recommended Git workflow:

```bash
git clone <private-repository-url>
cd HyperGrid_Battery_Digital_Twin_v0.2_PORTABLE
git checkout -b your-feature-name
# edit files
git add .
git commit -m "Describe the change"
git push -u origin your-feature-name
```

Merge through a pull request. Keep `main` runnable.

Suggested branches for the next phases: `battery-physics`, `hppc-identification`, `converter-validation`, `thermal-aging`, `excel-datasets`, `frontend`, then later `fuel-cell`, `ev`, `pv`, `wind`, and `multi-microgrid`.
