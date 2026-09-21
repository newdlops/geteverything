"""Import the selected checkpoint and reuse only unchanged zero-LoRA controls."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tarfile
import time

os.umask(0o077)
root=Path('/var/lib/geteverything-product-training')
source=Path('/usr/local/lib/geteverything-product-training')
stage=Path('/root/product-training-final-checkpoint-20260922')
with Path('/run/geteverything-product-training.lock').open('w') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    spec=importlib.util.spec_from_file_location('runner',source/'runner.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    assert not any((runner.state(name) or {}).get('Running') for name in (runner.TRAINER,runner.EVALUATOR))
    stage.mkdir(exist_ok=False)
    with tarfile.open('/tmp/product-training-v6-final.tar.gz') as archive:archive.extractall(stage,filter='data')
    for name,digest in json.loads((stage/'manifest.json').read_text()).items():
        path=stage/name
        assert path.resolve().is_relative_to(stage)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
    trained=json.loads((stage/'training/status.json').read_text())
    data=json.loads((stage/'training/dataset.json').read_text())
    runner.validate_import(trained,data,json.loads((root/'downloaded.json').read_text()),stage/'training')
    parent=root/'runs'/trained['selection_parent_run_id']
    previous=json.loads((root/'status.json').read_text())
    assert previous['run_id']==parent.name and previous['status']=='rejected'
    context=json.loads((parent/'generation-context.json').read_text())
    assert context['dataset_sha256']==data['sha256']==previous['dataset_sha256']
    assert context['baseline_adapter'] is None and context['version']=='generation-eval-4'
    assert context['endpoint']=='http://127.0.0.1:8095' and context['prompt_version']==trained['prompt_version']
    protocol_files=[source/'evaluate.py',*[source/'categories'/name for name in ('llm.py','rules.py','taxonomy.py','vocabulary.py')],
        source/'metrics/parser.py',*[source/'products'/name for name in ('identity.py','local_model.py','sft.py','sft_validation.py')]]
    assert hashlib.sha256(b''.join(path.read_bytes() for path in protocol_files)).hexdigest()==context['protocol_sha256']
    runtime=json.loads(Path('/etc/geteverything-categories/runtime.json').read_text())
    assert not runtime.get('product_lora_file'),'The operating baseline changed'
    assert runtime['model_image']=='ghcr.io/ggml-org/llama.cpp@sha256:b97738dc7c62a5eefbfc2f910ff727cc2bcc7dbe9e613d95532fcc32f9374025'
    digest=hashlib.sha256()
    with Path(runtime['model_file']).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    assert digest.hexdigest()=='aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223'
    assert hashlib.sha256((parent/'adapter.gguf').read_bytes()).hexdigest()==context['adapter_sha256']
    details=json.loads((parent/'generation-progress.json').read_text())
    controls=details[:2*len(data['validation'])]
    assert len(details)==3*len(data['validation'])
    expected=[(mode,row) for mode in ('baseline','same_prompt_base') for row in data['validation']]
    for actual,(mode,row) in zip(controls,expected):
        assert actual['mode']==mode and actual['title']==row['title'] and actual['expected']==row['target']
        assert actual.get('generated'),'Do not reuse transport failures'
        actual['source_inference_reused']=actual.get('inference_reused',False)
        actual['inference_reused']=True
        actual['control_reuse_source_run_id']=parent.name
    backup=stage/'before-import';backup.mkdir()
    for name in ('status.json','dataset.json','attempt.json'):shutil.copy2(root/name,backup/name)
    work=root/'runs'/trained['run_id']
    assert not work.exists()
    shutil.copytree(stage/'training/runs'/trained['run_id'],work)
    adapter_sha=hashlib.sha256((work/'adapter.gguf').read_bytes()).hexdigest()
    assert adapter_sha=='9ec27564330bddc935ef77edffcb7a13033cdbdc8085d5082ad605bfc4ca9035'
    proof={'source_run_id':parent.name,'rows':len(controls),'modes':['baseline','same_prompt_base'],
        'source_context_sha256':hashlib.sha256((parent/'generation-context.json').read_bytes()).hexdigest(),
        'source_progress_sha256':hashlib.sha256((parent/'generation-progress.json').read_bytes()).hexdigest(),
        'protocol_sha256':context['protocol_sha256'],'dataset_sha256':data['sha256'],
        'base_gguf_sha256':digest.hexdigest(),'model_image':runtime['model_image'],
        'reason':'Both controls explicitly disable every LoRA adapter; only candidate weights changed',
        'at':time.time()}
    shutil.copy2(parent/'generation-context.json',work/'control-source-context.json')
    shutil.copy2(parent/'generation-progress.json',work/'control-source-progress.json')
    new_context=context|{'run_id':trained['run_id'],'adapter_sha256':adapter_sha}
    runner.atomic(work/'generation-context.json',new_context)
    runner.atomic(work/'generation-progress.json',controls)
    runner.atomic(work/'control-reuse.json',proof)
    trained['control_reuse']=proof
    runner.atomic(root/'dataset.json',data)
    runner.atomic(root/'status.json',trained)
    runner.publish(trained)
    report={'run_id':trained['run_id'],'status':'imported_awaiting_candidate_evaluation',
        'adapter_gguf_sha256':adapter_sha,'control_rows_reused':len(controls),'at':time.time()}
    runner.atomic(stage/'deployment.json',report)
    print(json.dumps(report))
