"""Fast software checks; do not establish physical calibration."""
import math
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET
from hypergrid.config import default_config, normalize_config
from hypergrid.simulator import simulate
from hypergrid.exporter import export_xlsx


class OutputContractTests(unittest.TestCase):
    def test_rejects_nonfinite_simulation_inputs(self):
        for key in ("duration_s", "dc_bus_target_v", "output_sample_rate_hz"):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(key=key, value=value):
                    config = default_config(); config["simulation"][key] = value
                    with self.assertRaisesRegex(ValueError, "finite"):
                        normalize_config(config)

    def test_duration_boundary(self):
        for value in (0, -1, 120.01):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_config({"simulation": {"duration_s": value}})
        self.assertEqual(normalize_config({"simulation": {"duration_s": 120}})["simulation"]["duration_s"], 120)

    def test_real_export_preserves_samples_and_seventeen_battery_columns(self):
        cfg = normalize_config({"simulation": {"duration_s": .032}})
        result = simulate(cfg)
        times = result["series"]["time_s"]
        self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
        self.assertLessEqual(abs(times[-1] - .032), result["derived"]["time_step_s"] * 1.01)
        self.assertTrue(all(math.isfinite(x) for x in result["series"]["bus_voltage_v"]))
        with tempfile.TemporaryDirectory() as folder:
            path = export_xlsx(result, Path(folder) / "test.xlsx")
            with zipfile.ZipFile(path) as book:
                self.assertIsNone(book.testzip())
                ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for member, columns in (("xl/worksheets/sheet4.xml", 3), ("xl/worksheets/sheet5.xml", 17)):
                    rows = ET.fromstring(book.read(member)).findall("s:sheetData/s:row", ns)
                    self.assertEqual(len(rows) - 1, len(times))
                    self.assertTrue(all(len(row) == columns for row in rows))

if __name__ == "__main__": unittest.main()
