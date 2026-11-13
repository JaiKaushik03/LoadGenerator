import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from city_server import Server, preflight
from hypergrid.city import default_city


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Server(("127.0.0.1", 0), Path(self.temp.name) / "jobs")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_run_download_and_missing_job(self):
        c = default_city()
        c["duration_s"] = 120
        req = Request(
            self.base + "/api/jobs",
            data=json.dumps(c).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req) as response:
            self.assertEqual(response.status, 202)
            job = json.load(response)
        for _ in range(100):
            with urlopen(self.base + "/api/jobs/" + job["id"]) as response:
                state = json.load(response)
            if state["status"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["interval_records"], 2)
        self.assertEqual(len(state["preview"]["points"]), 2)
        self.assertGreaterEqual(state["runtime_s"], 0)
        for suffix in ["xlsx", "jsonl", "metadata"]:
            with urlopen(
                self.base + "/api/jobs/" + job["id"] + "/" + suffix
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())
        with self.assertRaises(HTTPError) as e:
            urlopen(self.base + "/api/jobs/not-a-real-job")
        self.assertEqual(e.exception.code, 404)

    def test_cross_origin_and_invalid_config(self):
        for headers, body, code in [
            (
                {
                    "Origin": "https://untrusted.example",
                    "Content-Type": "application/json",
                },
                b"{}",
                403,
            ),
            ({"Content-Type": "text/plain"}, b"{}", 415),
            ({"Content-Type": "application/json"}, b"{}", 400),
        ]:
            with self.subTest(code=code), self.assertRaises(HTTPError) as e:
                urlopen(Request(self.base + "/api/jobs", data=body, headers=headers))
            self.assertEqual(e.exception.code, code)

    def test_browser_budget_and_bind_guard(self):
        c = default_city()
        c["duration_s"] = 10000000
        with self.assertRaises(ValueError):
            preflight(c)
        with self.assertRaises(ValueError):
            Server(("0.0.0.0", 0), self.temp.name)

    def test_coupled_mode_presets_and_download(self):
        from test_coupled import scenario

        with urlopen(self.base + "/api/config?mode=hybrid") as response:
            preset = json.load(response)
        self.assertTrue(preset["nodes"][1]["thermal"])
        city, emt = scenario()
        body = {"city": city, "electrical": emt, "resource_interval_s": 0.01}
        req = Request(
            self.base + "/api/jobs/coupled",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req) as response:
            job = json.load(response)
        for _ in range(100):
            with urlopen(self.base + "/api/jobs/" + job["id"]) as response:
                state = json.load(response)
            if state["status"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["mode"], "coupled")
        self.assertTrue(state["preview"]["points"])
        with urlopen(self.base + "/api/jobs/" + job["id"] + "/xlsx") as response:
            self.assertTrue(response.read().startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
