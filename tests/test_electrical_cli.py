import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET
from electrical_cli import run, export_run
from hypergrid.emt import default_network


class ElectricalCLITests(unittest.TestCase):
    def test_run_export_and_existing_run_protection(self):
        c = default_network()
        c["duration_s"] = 0.004
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "run"
            result = run(c, folder, "emt")
            self.assertEqual(result["status"], "complete")
            rows = [
                json.loads(s)
                for s in (folder / "intervals.jsonl").read_text().splitlines()
            ]
            self.assertAlmostEqual(rows[-1]["time_s"], 0.004)
            exported = export_run(folder, folder / "emt.xlsx")
            self.assertEqual(exported["records"]["nodes"], len(rows))
            with zipfile.ZipFile(folder / "emt.xlsx") as archive:
                self.assertIsNone(archive.testzip())
                for name in archive.namelist():
                    ET.fromstring(archive.read(name))
            with self.assertRaises(FileExistsError):
                run(c, folder, "emt")
            from hypergrid.preview import preview

            self.assertTrue(preview(folder)["points"])
            with (folder / "intervals.jsonl").open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaises(ValueError):
                export_run(folder, folder / "corrupt.xlsx")
            self.assertFalse((folder / "corrupt.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
