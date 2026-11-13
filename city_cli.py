"""Stream auditable interval records; never overwrite an existing run directory."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import time
from hypergrid.city import CityModel, default_city


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-example', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.write_example:
        with args.write_example.open('x', encoding='utf-8') as f:
            json.dump(default_city(), f, indent=2, allow_nan=False)
        return
    if not args.output:
        parser.error('--output is required for simulation')
    config = json.loads(args.config.read_text(encoding='utf-8')) if args.config else default_city()
    result = run(config, args.output)
    print(json.dumps({k: result[k] for k in ['status', 'interval_records', 'runtime_s', 'totals']}, indent=2))


def run(config, output):
    output = Path(output)
    model = CityModel(config)
    output.mkdir(parents=True, exist_ok=False)
    canonical = json.dumps(config, sort_keys=True, allow_nan=False).encode()
    source_hash = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for name in ['city_cli.py', 'hypergrid/city.py', 'hypergrid/energy.py']:
        source_hash.update(name.encode())
        source_hash.update((root/name).read_bytes())
    metadata = {'status': 'running', 'fidelity': 'energy_balance',
                'config_sha256': hashlib.sha256(canonical).hexdigest(),
                'source_sha256': source_hash.hexdigest(),
                'python': platform.python_version(), 'platform': platform.platform(),
                'config': config,
                'limitations': ['Not a circuit/load-flow solver or calibrated lunar digital twin',
                                'Ordered direct transfers; no multihop routing or optimal dispatch',
                                'Resource capacity and efficiency models, not full resource dynamics',
                                'No coupled thermal, communications, autonomous-agent or CHIL model',
                                'No two-way coupling to the separate explicit-PWM battery solver']}
    meta_path = output/'metadata.json'
    meta_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    start = time.perf_counter()
    rows = 0
    totals = {'generation_kwh': 0., 'served_kwh': 0., 'unserved_kwh': 0.,
              'curtailed_kwh': 0., 'transmission_loss_kwh': 0., 'storage_loss_kwh': 0.,
              'max_abs_bus_balance_residual_kw': 0.}
    try:
        with (output/'intervals.jsonl').open('x', encoding='utf-8') as f:
            for record in model.intervals():
                f.write(json.dumps(record, allow_nan=False, separators=(',', ':'))+'\n')
                rows += 1
                c = record['city']
                h = record['dt_s']/3600
                for key in ['generation', 'served', 'unserved', 'curtailed', 'transmission_loss']:
                    totals[key+'_kwh'] += c[key+'_kw']*h
                totals['storage_loss_kwh'] += c['storage_loss_kwh']
                totals['max_abs_bus_balance_residual_kw'] = max(
                    totals['max_abs_bus_balance_residual_kw'], abs(c['balance_residual_kw']))
        metadata.update(status='complete', interval_records=rows, totals=totals,
                        runtime_s=time.perf_counter()-start)
    except BaseException as exc:
        metadata.update(status='failed', completed_interval_records=rows, error=type(exc).__name__)
        raise
    finally:
        temp = meta_path.with_suffix('.tmp')
        temp.write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding='utf-8')
        temp.replace(meta_path)
    return metadata


if __name__ == '__main__':
    main()
