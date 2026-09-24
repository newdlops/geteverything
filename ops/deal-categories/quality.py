#!/usr/bin/env python3
"""Run the read-only product audit outside the memory-limited live worker."""
import json
from pathlib import Path
import subprocess


def main():
    config=json.loads(Path('/etc/geteverything-categories/runtime.json').read_text())
    command=['docker','run','--rm','--name','geteverything-product-quality',
             '--network=host','--read-only','--user=65534:65534',
             '--cap-drop=ALL','--security-opt=no-new-privileges',
             '--memory=192m','--memory-swap=192m','--cpus=0.3',
             '--tmpfs=/tmp:rw,nosuid,nodev,size=16m',
             '--env-file=/etc/geteverything-categories/worker.env',
             config['worker_image'],'python','-m','gadmin.products.manage','audit','--limit','12']
    subprocess.run(command,check=True,timeout=300)


if __name__=='__main__':main()
