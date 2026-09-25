from __future__ import annotations

import json
import mimetypes
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from hypergrid.config import default_config
from hypergrid.exporter import export_xlsx
from hypergrid.simulator import BATTERY_CATALOG, SEMICONDUCTOR_CATALOG, jsonify_result, simulate

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(exist_ok=True)
RUNS: dict[str, dict] = {}
HOST = "127.0.0.1"
PORT = 8000


class Handler(BaseHTTPRequestHandler):
    server_version = "HyperGridPortable/0.2"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, obj, status=200):
        data = json.dumps(obj, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, message, status=400):
        self._json({"detail": str(message)}, status)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/default-config":
            return self._json(default_config())
        if path == "/api/catalog":
            return self._json({"batteries": BATTERY_CATALOG, "semiconductors": SEMICONDUCTOR_CATALOG})
        if path == "/api/model-notes":
            try:
                with open(ROOT / "data" / "sources.json", "r", encoding="utf-8") as f:
                    sources = json.load(f)
            except Exception:
                sources = {}
            return self._json({
                "engine": "HyperGrid Portable custom explicit-PWM electrothermal solver written in Python standard library only.",
                "battery": "SOC/temperature/SOH-dependent 2-RC ECM with OCV hysteresis, thermal dynamics and throughput aging.",
                "converter": "Bidirectional non-isolated switching leg with explicit PWM state, dead time, conduction loss, switching-energy scaling and junction thermal state.",
                "network": "Temperature-corrected cable resistance, geometry-derived loop inductance, contactor/fuse resistance, converter inductor ESR and DC-link capacitor ESR.",
                "control": "DC-bus power PI plus per-battery current PI and selectable sharing.",
                "important": "Cell-specific dynamic truth still requires HPPC/EIS/thermal calibration; seed parameters remain labeled as such.",
                "sources": sources,
            })
        if path.startswith("/api/export/") and path.endswith(".xlsx"):
            run_id = path.split("/")[-1][:-5]
            result = RUNS.get(run_id)
            if result is None:
                return self._error("Run not found in this server session", 404)
            out = OUTPUTS / f"hypergrid_{run_id}.xlsx"
            try:
                export_xlsx(result, out)
                return self._send_file(out, download_name=out.name)
            except Exception as exc:
                return self._error(f"Excel export failed: {exc}", 500)
        return self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/simulate":
            return self._error("Not found", 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10_000_000:
                raise ValueError("Invalid request body size")
            raw = self.rfile.read(length)
            cfg = json.loads(raw.decode("utf-8"))
            result = simulate(cfg)
            RUNS[result["run_id"]] = result
            return self._json(jsonify_result(result))
        except ValueError as exc:
            return self._error(exc, 400)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return self._error(f"Simulation failed: {exc}", 500)

    def _serve_static(self, path: str):
        if path in ("", "/"):
            file = STATIC / "index.html"
        else:
            rel = unquote(path.lstrip("/"))
            file = (STATIC / rel).resolve()
            if STATIC.resolve() not in file.parents and file != STATIC.resolve():
                return self._error("Forbidden", 403)
        if not file.exists() or not file.is_file():
            return self._error("Not found", 404)
        return self._send_file(file)

    def _send_file(self, path: Path, download_name: str | None = None):
        data = path.read_bytes()
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def open_browser():
    try:
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass


def main():
    global PORT
    os.chdir(ROOT)
    server = None
    for candidate in range(8000, 8011):
        try:
            server = ThreadingHTTPServer((HOST, candidate), Handler)
            PORT = candidate
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("Could not open a local port from 8000 through 8010. Close another HyperGrid/server instance and try again.")
    print("\n============================================================")
    print(" HyperGrid Battery Digital Twin v0.2 PORTABLE")
    print(" Zero external packages | Explicit PWM | Excel export")
    print("============================================================")
    print(f"\nOpen: http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop the server.\n")
    threading.Timer(0.8, open_browser).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping HyperGrid...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
