#!/usr/bin/env python3
"""Verify real weight updates, GGUF conversion and local inference without promotion."""
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import time
import urllib.request

import runner


def main():
    def interrupted(*_):
        raise InterruptedError('Probe interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    root=runner.ROOT
    config=json.loads(Path('/etc/geteverything-product-training.json').read_text())
    policy=runner.training_policy(config)
    with Path('/run/geteverything-product-training.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        active=(root/'active.json').read_bytes() if (root/'active.json').exists() else None
        try:
            runner.lease(True)
            runner.run(['python3','/usr/local/lib/geteverything-categories/guard.py'])
            runner.command(config,['python','/training-code/train.py','--dataset','/training/dataset.json',
                '--probe','--epochs','1','--max-steps','2','--rank',str(policy['rank']),
                '--learning-rate',str(policy['learning_rate'])],cpu=str(policy['cpu']))
            runner.wait(runner.TRAINER,20*60)
            trained=json.loads((root/'status.json').read_text())
            assert trained['status']=='probe_complete' and trained['step']==2 and trained['lora_b_squared_norm']>0
            runner.publish(trained)
            work='/training/runs/'+trained['run_id']
            assert trained['adapter']==work+'/best'
            runner.command(config,['python','/training/tools/convert_lora_to_gguf.py','--base','/training/base',
                '--outfile',work+'/adapter.gguf',trained['adapter']],memory='1g')
            runner.wait(runner.TRAINER,300)
            runtime=json.loads(Path('/etc/geteverything-categories/runtime.json').read_text())
            runner.cleanup(runner.EVALUATOR)
            adapter=root/'runs'/trained['run_id']/'adapter.gguf'
            runner.run(['docker','run','-d','--name',runner.EVALUATOR,'--init','--network=host','--read-only',
                '--cap-drop=ALL','--security-opt=no-new-privileges','--cpus='+str(policy['evaluation_cpu']),
                '--memory=3g','--memory-swap=3g','--pids-limit=64','--oom-score-adj=800','--no-healthcheck',
                '--tmpfs=/tmp:rw,nosuid,nodev,size=32m','--log-driver=local','--log-opt=max-size=2m','--log-opt=max-file=2',
                '--mount=type=bind,src='+runtime['model_file']+',dst=/models/base.gguf,readonly',
                '--mount=type=bind,src='+str(adapter)+',dst=/models/adapter.gguf,readonly',runtime['model_image'],
                '-m','/models/base.gguf','--lora','/models/adapter.gguf','--lora-init-without-apply',
                '--host','127.0.0.1','--port','8095','--alias','category-local','--threads','1','--threads-batch','1',
                '--ctx-size','2048','--parallel','1','--batch-size','256','--ubatch-size','64','--poll','0',
                '--poll-batch','0','--jinja','--no-webui'])
            for attempt in range(3):
                runner.lease(True);time.sleep(20)
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8095/health',timeout=10) as response:
                        assert response.status==200
                    break
                except (OSError,AssertionError):
                    if attempt==2:raise
            code='''import json
from gadmin.categories.llm import LocalModel
from gadmin.categories.taxonomy import GROUPS
from gadmin.products.sft import SYSTEM,FIELDS
properties={k:{'type':'string','maxLength':160} for k in ('brand','name','model','variant')}
properties.update(is_product={'type':'boolean'},category={'type':'string','enum':[*GROUPS,'unknown']})
schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
result=LocalModel(endpoint='http://127.0.0.1:8095',timeout=240).structured(SYSTEM,{'title':'삼성 990 PRO 1TB'},schema,224,adapter=0)
assert set(result)==FIELDS and isinstance(result['is_product'],bool)
print(json.dumps({'adapter_inference':True,'output':result},ensure_ascii=False))
'''
            runner.command(config,['python','-c',code],network='host',memory='192m',cpu='0.05')
            runner.wait(runner.TRAINER,300)
            inference=json.loads(runner.run(['docker','logs',runner.TRAINER]).splitlines()[-1])
            assert ((root/'active.json').read_bytes() if (root/'active.json').exists() else None)==active
            result={'at':time.time(),'technical_probe':True,'promoted':False,
                'run_id':trained['run_id'],'steps':trained['step'],'trainable_parameters':trained['trainable_parameters'],
                'lora_b_squared_norm':trained['lora_b_squared_norm'],'recipe':trained['recipe'],
                'gguf_sha256':hashlib.sha256(adapter.read_bytes()).hexdigest(),
                'last_cache_seconds':trained.get('last_cache_seconds'),'last_step_seconds':trained.get('last_step_seconds'),
                **inference}
            runner.atomic(root/'probe-verification.json',result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
        finally:
            for name in (runner.TRAINER,runner.EVALUATOR):
                state=runner.state(name)
                if state and state['Running']:
                    if state['Paused']:runner.run(['docker','unpause',name])
                    runner.run(['docker','stop','--time','45',name],60)
            runner.lease(False)


if __name__=='__main__':main()
