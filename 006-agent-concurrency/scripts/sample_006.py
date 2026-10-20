#!/usr/bin/env python3
"""005 GPU measurements plus host /proc CPU/RAM, once per second on Linux."""
import json
import signal
import sys
import time
from pathlib import Path
import gpu_sampler

running = True

def stop(*_):
    global running
    running = False


def cpu():
    values = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    path = Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True)
    engine, level = sys.argv[2:4]
    if len(sys.argv) == 5:
        sample = gpu_sampler.sample(engine)
        sample.update(level=level, boundary=sys.argv[4])
        with path.open('a') as out:
            out.write(json.dumps(sample) + '\n')
        return
    before = cpu()
    with path.open('a') as out:
        while running:
            sample = gpu_sampler.sample(engine)
            sample['level'] = level
            after = cpu(); total = after[0] - before[0]
            sample['host_cpu_percent'] = 100 * (1 - (after[1] - before[1]) / total) if total else None
            before = after
            mem = {k: int(v.split()[0]) for k, v in (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}
            sample['host_ram_used_mb'] = (mem['MemTotal'] - mem['MemAvailable']) / 1024
            out.write(json.dumps(sample) + '\n'); out.flush()
            for _ in range(10):
                if not running:
                    break
                time.sleep(.1)


if __name__ == '__main__':
    main()
