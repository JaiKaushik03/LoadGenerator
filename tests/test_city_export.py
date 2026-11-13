import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile
from city_export import export_xlsx
from hypergrid.city import default_city, CityModel


class ExportTests(unittest.TestCase):
    def test_split_without_losing_records_and_preserve_formula_as_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            c = default_city()
            c['duration_s'] = 120
            c['nodes'][0]['sources'][0]['id'] = '=1+1'
            rows = list(CityModel(c).intervals())
            (p/'metadata.json').write_text(json.dumps({'status':'complete','config':c}))
            (p/'intervals.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            out = p/'city.xlsx'
            result = export_xlsx(p, out, row_limit=10)
            self.assertEqual(result['records']['city'], 2)
            self.assertEqual(result['records']['nodes'], 14)
            self.assertEqual(result['records']['assets'], 56)
            self.assertEqual(result['records']['ties'], 12)
            with zipfile.ZipFile(out) as z:
                self.assertIsNone(z.testzip())
                for name in z.namelist():
                    ET.fromstring(z.read(name))
                xml = b''.join(z.read(n) for n in z.namelist() if '/worksheets/' in n)
                self.assertIn(b'=1+1', xml)
                self.assertNotIn(b'<f>', xml)
            with self.assertRaises(FileExistsError):
                export_xlsx(p, out)


if __name__ == '__main__':
    unittest.main()
