import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile
import hashlib
import csv
from city_csv import export_csv
from city_export import export_xlsx, cell
from hypergrid.city import default_city, CityModel


class ExportTests(unittest.TestCase):
    def test_invalid_xml_codepoints_are_removed_but_valid_unicode_survives(self):
        xml = cell("A1", "Moon \U0001f319\x00\ud800\ufffe")
        parsed = ET.fromstring(xml)
        self.assertEqual("".join(parsed.itertext()), "Moon \U0001f319")

    def make_run(self, path):
        config = default_city()
        config["duration_s"] = 60
        config["nodes"][0]["sources"][0]["id"] = "=1+1"
        data = "".join(
            json.dumps(r) + "\n" for r in CityModel(config).outputs()
        ).encode()
        (path / "intervals.jsonl").write_bytes(data)
        meta = {
            "status": "complete",
            "dataset_sha256": hashlib.sha256(data).hexdigest(),
            "config": config,
            "large_metadata": list(range(12000)),
        }
        (path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    def test_csv_counts_hashes_and_literal_strings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.make_run(path)
            result = export_csv(path, path / "csv")
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["tables"]["assets"]["rows"], 28)
            for table in result["tables"].values():
                self.assertEqual(
                    table["sha256"],
                    hashlib.sha256(
                        (path / "csv" / table["file"]).read_bytes()
                    ).hexdigest(),
                )
            with (path / "csv/assets.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(any("'=1+1" in row.values() for row in rows))
            exported = export_xlsx(path, path / "data.xlsx")
            self.assertGreater(exported["records"]["metadata"], 12000)

    def test_corrupt_dataset_is_rejected_before_workbook_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.make_run(path)
            with (path / "intervals.jsonl").open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                export_xlsx(path, path / "bad.xlsx")
            self.assertFalse((path / "bad.xlsx").exists())

    def test_split_without_losing_records_and_preserve_formula_as_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            c = default_city()
            c["duration_s"] = 120
            c["nodes"][0]["sources"][0]["id"] = "=1+1"
            rows = list(CityModel(c).intervals())
            (p / "metadata.json").write_text(
                json.dumps({"status": "complete", "config": c})
            )
            (p / "intervals.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows)
            )
            out = p / "city.xlsx"
            result = export_xlsx(p, out, row_limit=10)
            self.assertEqual(result["records"]["city"], 2)
            self.assertEqual(result["records"]["nodes"], 14)
            self.assertEqual(result["records"]["assets"], 56)
            self.assertEqual(result["records"]["ties"], 12)
            with zipfile.ZipFile(out) as z:
                self.assertIsNone(z.testzip())
                for name in z.namelist():
                    ET.fromstring(z.read(name))
                xml = b"".join(z.read(n) for n in z.namelist() if "/worksheets/" in n)
                self.assertIn(b"=1+1", xml)
                self.assertNotIn(b"<f>", xml)
            with self.assertRaises(FileExistsError):
                export_xlsx(p, out)


if __name__ == "__main__":
    unittest.main()
