#!/usr/bin/env python3
"""Download a pinned official checkpoint; training itself runs without network."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import urllib.request

ROOT = Path('/var/lib/geteverything-product-training')
REPO = 'Qwen/Qwen3.5-2B'


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.load(response)
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2)


def download(row, revision, destination):
    name = row['rfilename']
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = row.get('lfs', {}).get('sha256')
    def checksum(path):
        digest = hashlib.sha256()
        with path.open('rb') as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()
    if target.is_file() and (not expected or checksum(target) == expected):
        return {'name': name, 'bytes': target.stat().st_size, 'sha256': expected}
    temporary = target.with_suffix(target.suffix + '.part')
    for attempt in range(3):
        try:
            digest = hashlib.sha256()
            total = 0
            started = time.monotonic()
            with urllib.request.urlopen(f'https://huggingface.co/{REPO}/resolve/{revision}/{name}', timeout=60) as response, temporary.open('wb') as output:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > 6 * 1024**3 or time.monotonic() - started > 3600:
                        raise RuntimeError('Checkpoint download limit exceeded')
                    digest.update(block)
                    output.write(block)
            if expected and digest.hexdigest() != expected:
                raise RuntimeError('Checkpoint checksum mismatch')
            temporary.replace(target)
            return {'name': name, 'bytes': total, 'sha256': digest.hexdigest()}
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    ROOT = args.root
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(ROOT).free < 12 * 1024**3:
        raise RuntimeError('At least 12 GiB free disk is required')
    manifest_path = ROOT / 'checkpoint.json'
    if manifest_path.exists():
        metadata = json.loads(manifest_path.read_text())
    else:
        metadata = fetch(f'https://huggingface.co/api/models/{REPO}?blobs=true')
        manifest_path.write_text(json.dumps(metadata, indent=2))
    revision = metadata['sha']
    assert len(revision) == 40 and metadata['id'] == REPO
    destination = ROOT / 'base'
    selected = [row for row in metadata['siblings'] if row['rfilename'] in {
        'config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json',
        'chat_template.jinja', 'vocab.json', 'merges.txt', 'model.safetensors.index.json',
    } or row['rfilename'].endswith('.safetensors')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        files = list(pool.map(lambda row: download(row, revision, destination), selected))
    result = {'repo': REPO, 'revision': revision, 'files': files, 'at': time.time()}
    (ROOT / 'downloaded.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'checkpoint_ready': True, 'revision': revision,
                      'files': len(files), 'bytes': sum(row['bytes'] for row in files)}), flush=True)


if __name__ == '__main__':
    main()
