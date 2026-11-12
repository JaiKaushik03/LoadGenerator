"""Reproduce local synthetic simulator timings and verify a real XLSX export.

This measures software throughput, not physical calibration or accuracy.
Run with bundled Python: benchmark_hypergrid.py --durations 3.2 30 120 --repeats 3
"""
from pathlib import Path
import argparse, gc, hashlib, json, math, platform, statistics, sys, time, zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hypergrid.config import default_config, normalize_config
from hypergrid.simulator import simulate
from hypergrid.exporter import export_xlsx

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--durations', nargs='+', type=float, default=[3.2, 30, 120])
    p.add_argument('--repeats', type=int, default=3)
    args = p.parse_args()
    out = ROOT / 'benchmark-output'; out.mkdir(parents=True, exist_ok=True)
    report = {'kind': 'synthetic software performance benchmark, not physical validation',
              'python': sys.version, 'platform': platform.platform(),
              'processor': platform.processor(), 'repeats': args.repeats, 'cases': [],
              'source_sha256': {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                                for f in sorted((ROOT / 'hypergrid').glob('*.py'))}}
    for duration in args.durations:
        cfg = default_config(); cfg['simulation']['duration_s'] = duration
        cfg = normalize_config(cfg)
        timings = []
        for repeat in range(args.repeats):
            gc.collect()
            start = time.perf_counter(); result = simulate(cfg); elapsed = time.perf_counter() - start
            times = result['series']['time_s']
            # The solver truncates to an integer integration grid; report the
            # actual terminal timestamp rather than pretending it is exact.
            dt = result['derived']['time_step_s']
            assert -1e-7 <= duration - times[-1] <= dt * 1.01 + 1e-7, (duration, times[-1], dt)
            assert all(math.isfinite(v) for v in result['series']['bus_voltage_v'])
            assert all(a < b for a, b in zip(times, times[1:]))
            timings.append(elapsed)
            print(json.dumps({'duration_s': duration, 'repeat': repeat + 1, 'runtime_s': round(elapsed, 4),
                              'time_samples': len(times)}), flush=True)
        case = {'duration_s': duration, 'actual_end_s': times[-1],
                'terminal_grid_gap_s': duration - times[-1], 'runtime_seconds': timings,
                'median_runtime_s': statistics.median(timings), 'time_samples': len(times),
                'output_interval_s': times[1] - times[0], 'integration_step_s': result['derived']['time_step_s'],
                'trips': [b['trip'] for b in result['summary']['battery_summaries']]}
        if duration == max(args.durations):
            start = time.perf_counter(); book = export_xlsx(result, out / 'HyperGrid_Benchmark.xlsx')
            case['xlsx_export_runtime_s'] = time.perf_counter() - start
            case['xlsx_bytes'] = book.stat().st_size
            case['xlsx_sha256'] = hashlib.sha256(book.read_bytes()).hexdigest()
            counts = {}
            with zipfile.ZipFile(book) as z:
                assert z.testzip() is None
                for member in ['xl/worksheets/sheet4.xml', 'xl/worksheets/sheet5.xml']:
                    rows = 0; first_columns = None
                    with z.open(member) as stream:
                        for _, element in ET.iterparse(stream, events=('end',)):
                            if element.tag.endswith('}row'):
                                if first_columns is None: first_columns = len(element)
                                rows += 1; element.clear()
                    counts[member] = {'data_rows': rows - 1, 'columns': first_columns}
            assert counts['xl/worksheets/sheet4.xml']['data_rows'] == len(times)
            assert counts['xl/worksheets/sheet5.xml']['data_rows'] == len(times)
            assert counts['xl/worksheets/sheet5.xml']['columns'] == 17
            case['verified_xlsx_sheets'] = counts
        report['cases'].append(case)
        (out / 'hypergrid_benchmark.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        del result; gc.collect()
    print('Completed benchmark and XLSX row verification.', flush=True)

if __name__ == '__main__': main()
