"""Loopback-only city scenario editor, bounded jobs and downloadable evidence."""
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import uuid
from urllib.parse import urlparse
from city_cli import run
from city_export import export_xlsx
from hypergrid.city import CityModel, default_city

ROOT = Path(__file__).resolve().parent


def preflight(config):
    CityModel(config)
    assets = sum(len(n['sources']) + len(n['loads']) + len(n['storage']) for n in config['nodes'])
    schedules = [x['availability'] for n in config['nodes'] for x in n['sources']]
    schedules += [x['demand'] for n in config['nodes'] for x in n['loads']]
    schedules += [x['availability'] for x in config['ties']]
    events = sum(len(s) for s in schedules)
    upper_steps = math.ceil(config['duration_s']/config['step_s']) + events
    upper_records = upper_steps * (1 + assets + len(config['nodes']) + len(config['ties']))
    if upper_records > 250000:
        raise ValueError('Browser jobs are limited to 250,000 estimated records; use city_cli.py for larger runs')


class Server(ThreadingHTTPServer):
    def __init__(self, address, output_root):
        if address[0] != '127.0.0.1':
            raise ValueError('City editor must bind to loopback')
        super().__init__(address, Handler)
        self.output_root = Path(output_root)
        self.jobs = {}
        self.job_lock = threading.Lock()
        self.busy = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data, status=200, mime='application/json'):
        if mime == 'application/json':
            data = json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            return self.respond((ROOT/'static/city.html').read_bytes(), mime='text/html; charset=utf-8')
        if path == '/api/config':
            return self.respond(default_city())
        parts = path.strip('/').split('/')
        if len(parts) >= 3 and parts[:2] == ['api', 'jobs']:
            job = self.server.jobs.get(parts[2])
            if not job:
                return self.respond({'error': 'Unknown job'}, 404)
            if len(parts) == 3:
                return self.respond(job)
            names = {'xlsx': 'city.xlsx', 'jsonl': 'intervals.jsonl', 'metadata': 'metadata.json'}
            if len(parts) == 4 and parts[3] in names and job['status'] == 'complete':
                file = self.server.output_root/parts[2]/names[parts[3]]
                mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if parts[3] == 'xlsx' else 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Disposition', f'attachment; filename="{file.name}"')
                self.send_header('Content-Length', str(file.stat().st_size))
                self.end_headers()
                with file.open('rb') as f:
                    while block := f.read(65536):
                        self.wfile.write(block)
                return
        return self.respond({'error': 'Not found'}, 404)

    def do_POST(self):
        port = self.server.server_address[1]
        if self.headers.get('Origin') not in [None, f'http://127.0.0.1:{port}']:
            return self.respond({'error': 'Cross-origin request denied'}, 403)
        if urlparse(self.path).path != '/api/jobs':
            return self.respond({'error': 'Not found'}, 404)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.respond({'error': 'JSON required'}, 415)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 1_000_000:
                raise ValueError('Invalid request size')
            config = json.loads(self.rfile.read(size))
            preflight(config)
        except (ValueError, TypeError, KeyError, OverflowError) as e:
            return self.respond({'error': str(e)}, 400)
        with self.server.job_lock:
            if self.server.busy:
                return self.respond({'error': 'A job is already running'}, 409)
            if len(self.server.jobs) >= 50:
                return self.respond({'error': 'Session job limit reached; restart the editor'}, 429)
            self.server.busy = True
            jid = uuid.uuid4().hex
            self.server.jobs[jid] = {'id': jid, 'status': 'running'}
        def worker():
            try:
                out = self.server.output_root/jid
                result = run(config, out)
                export_xlsx(out, out/'city.xlsx')
                self.server.jobs[jid] = {'id': jid, 'status': 'complete',
                                         'totals': result['totals'], 'interval_records': result['interval_records']}
            except Exception as e:
                self.server.jobs[jid] = {'id': jid, 'status': 'failed', 'error': type(e).__name__}
            finally:
                with self.server.job_lock:
                    self.server.busy = False
        threading.Thread(target=worker, daemon=True).start()
        self.respond({'id': jid, 'status': 'running'}, 202)


if __name__ == '__main__':
    server = Server(('127.0.0.1', 8012), ROOT/'outputs/city-browser')
    print('City editor: http://127.0.0.1:8012 — energy mode; not calibrated full-city physics')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
