#!/usr/bin/env python3
"""Keep inference unloaded while the crawler needs CPU or memory."""
import json
import hashlib
from pathlib import Path
import subprocess
import time

ROOT = Path('/var/lib/geteverything-categories')
NAME = 'geteverything-category-model'


def run(args, check=True):
    return subprocess.run(args, capture_output=True, text=True, timeout=20, check=check)


def decision(cpu, available, pending, running, low_count, training=False):
    # A 0.20-core model uses up to 10% of this 2-vCPU host. Start below 60%
    # and stop at 80%, preserving headroom with a wide hysteresis band.
    if training or available < 3 * 1024**3 or cpu >= 80 or not pending:
        return False, 0
    low_count = low_count + 1 if cpu < 60 and available >= 4 * 1024**3 else 0
    return (running or low_count >= 2), low_count


def main():
    config = json.loads(Path('/etc/geteverything-categories/runtime.json').read_text())
    state_path = ROOT / 'guard.json'
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = time.time()
    ticks = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    total, idle = sum(ticks), ticks[3] + ticks[4]
    delta = total - previous.get('total', total)
    cpu = 100 * (1 - (idle - previous.get('idle', idle)) / delta) if delta > 0 else 100
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    try:
        demand = json.loads((ROOT / 'state' / 'demand.json').read_text())
    except (OSError, ValueError):
        demand = {}
    pending = demand.get('pending', 0) if now - demand.get('at', 0) < 180 else 0
    try:
        lease = json.loads((ROOT / 'state' / 'product-training.json').read_text())
    except (OSError, ValueError):
        lease = {}
    training_state = run(['docker', 'inspect', '--format', '{{.State.Running}}',
                          'geteverything-product-trainer'], check=False)
    training = ((lease.get('active') is True and now-lease.get('at', 0)<90) or
                (training_state.returncode == 0 and training_state.stdout.strip() == 'true'))
    inspected = run(['docker', 'inspect', '--format', '{{.State.Running}}', NAME], check=False)
    running = inspected.returncode == 0 and inspected.stdout.strip() == 'true'
    if inspected.returncode == 0:
        quota=run(['docker','inspect','--format','{{.HostConfig.NanoCpus}}',NAME]).stdout.strip()
        if quota!='200000000':run(['docker','update','--cpus=0.20',NAME])
    wanted, low_count = decision(cpu, available, pending, running, previous.get('low_count', 0), training)
    if wanted and inspected.returncode != 0:
        model = Path(config['model_file'])
        if not model.is_file() or not str(model).startswith(str(ROOT / 'models') + '/'):
            raise RuntimeError('Configured local model is missing')
        adapter_mounts=[];adapter_args=[]
        if config.get('product_lora_file'):
            adapter=Path(config['product_lora_file'])
            if (not adapter.is_file() or not str(adapter.resolve()).startswith(str(ROOT/'models'/'adapters')+'/') or
                    adapter.stat().st_size>32*1024**2 or
                    hashlib.sha256(adapter.read_bytes()).hexdigest()!=config.get('product_lora_sha256')):
                raise RuntimeError('Validated product adapter is missing or has changed')
            adapter_mounts=['--mount=type=bind,src='+str(adapter)+',dst=/models/product-adapter.gguf,readonly']
            adapter_args=['--lora','/models/product-adapter.gguf','--lora-init-without-apply']
        run(['docker', 'create', '--name', NAME, '--init', '--network=host', '--read-only', '--user=65534:65534',
             '--cap-drop=ALL', '--security-opt=no-new-privileges', '--memory=3g', '--memory-swap=3g',
             '--cpus=0.20', '--cpu-shares=128', '--pids-limit=64', '--oom-score-adj=500',
             '--tmpfs=/tmp:rw,nosuid,nodev,size=32m', '--log-driver=local', '--log-opt=max-size=2m', '--log-opt=max-file=2',
             '--mount=type=bind,src=' + str(model) + ',dst=/models/classifier.gguf,readonly',
             *adapter_mounts,
             config['model_image'], '-m', '/models/classifier.gguf', '--host', '127.0.0.1', '--port', '8094',
             '--alias', 'category-local', '--threads', '1', '--threads-batch', '1', '--ctx-size', '2048',
             '--parallel', '1', '--batch-size', '256', '--ubatch-size', '64', '--poll', '0', '--poll-batch', '0', '--jinja', '--no-webui',*adapter_args])
    if wanted and not running:
        run(['docker', 'start', NAME])
    elif running and not wanted:
        run(['docker', 'stop', '--time', '5', NAME])
    record = {'at': now, 'cpu_percent': round(cpu, 1), 'memory_available': available, 'pending': pending,
              'model_enabled': wanted, 'training_active':training, 'low_count': low_count, 'total': total, 'idle': idle}
    temporary = state_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record))
    temporary.replace(state_path)
    print(json.dumps({k: v for k, v in record.items() if k not in ('total', 'idle')}))


if __name__ == '__main__':
    main()
