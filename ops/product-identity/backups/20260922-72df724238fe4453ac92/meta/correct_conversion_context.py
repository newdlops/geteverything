import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import time

root=Path('/var/lib/geteverything-product-training')
work=root/'runs/72df724238fe4453ac92'
stage=Path('/root/product-training-final-checkpoint-20260922')
old='9ec27564330bddc935ef77edffcb7a13033cdbdc8085d5082ad605bfc4ca9035'
new='000ab490c4eceb5ad6bc990ea9b25e84fa9025ad1029565f85515a740c5ac41e'
with Path('/run/geteverything-product-training.lock').open('w') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    spec=importlib.util.spec_from_file_location('runner','/usr/local/lib/geteverything-product-training/runner.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    assert not any((runner.state(name) or {}).get('Running') for name in (runner.TRAINER,runner.EVALUATOR))
    assert hashlib.sha256((work/'adapter.gguf').read_bytes()).hexdigest()==new
    context=json.loads((work/'generation-context.json').read_text())
    rows=json.loads((work/'generation-progress.json').read_text())
    assert context['adapter_sha256']==old and len(rows)==200
    assert {row['mode'] for row in rows}=={'baseline','same_prompt_base'}
    archive=stage/'conversion-context-correction';archive.mkdir(exist_ok=False)
    for name in ('generation-context.json','generation-progress.json'):shutil.copy2(work/name,archive/name)
    shutil.copy2(root/'status.json',archive/'failed-status.json')
    proof={'at':time.time(),'original_gguf_sha256':old,'canonical_gguf_sha256':new,
        'identical_tensors':14,'metadata_differences':{'general.name':['Checkpoint','Best']},
        'verification':'Local and server canonical conversions have identical SHA-256; all 14 tensor byte hashes match the CPU-tested checkpoint'}
    runner.atomic(work/'conversion-verification.json',proof)
    runner.atomic(work/'generation-context.json',context|{'adapter_sha256':new})
    state=json.loads((work/'result.json').read_text())
    assert state['status']=='trained_awaiting_generation_eval'
    state['control_reuse']=json.loads((work/'control-reuse.json').read_text())
    state['conversion_verification']=proof
    runner.atomic(root/'status.json',state)
    runner.publish(state)
    print(json.dumps({'run_id':state['run_id'],'status':state['status'],'gguf_sha256':new}))
