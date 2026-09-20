#!/usr/bin/env python3
"""Keep the adapter converter at the same revision as the inference binary."""
import io
from pathlib import Path, PurePosixPath
import tarfile
import time
import urllib.request

REVISION = 'aa39d7a3e145a88202793a89462d65e94a5fc25f'


def main():
    target=Path('/var/lib/geteverything-product-training/tools')
    target.mkdir(parents=True,exist_ok=True)
    if (target/'revision').is_file():
        assert (target/'revision').read_text()==REVISION
        return
    for attempt in range(3):
        try:
            with urllib.request.urlopen('https://codeload.github.com/ggml-org/llama.cpp/tar.gz/'+REVISION,timeout=60) as response:
                payload=response.read(80*1024*1024+1)
            if len(payload)>80*1024*1024:raise RuntimeError('Converter source archive exceeds size limit')
            break
        except OSError:
            if attempt==2:raise
            time.sleep(2)
    count=0
    with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
        for entry in archive:
            path=PurePosixPath(entry.name)
            parts=path.parts[1:]
            if not entry.isfile() or not parts or '..' in parts:continue
            relative=PurePosixPath(*parts)
            if (relative.name not in ('convert_lora_to_gguf.py','convert_hf_to_gguf.py') and
                    relative.parts[0] not in ('conversion','gguf-py')):continue
            if entry.size>8*1024*1024:raise RuntimeError('Unexpected converter source file size')
            destination=target/str(relative)
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(archive.extractfile(entry).read())
            count+=1
    assert (target/'convert_lora_to_gguf.py').is_file() and count>10
    (target/'revision').write_text(REVISION)
    print('Pinned adapter converter ready',flush=True)


if __name__=='__main__':main()
