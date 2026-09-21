#!/usr/bin/env python3
"""Bounded, resumable local training, held-out evaluation, and guarded promotion."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import urllib.request

ROOT=Path('/var/lib/geteverything-product-training')
SOURCE=Path('/usr/local/lib/geteverything-product-training')
CATEGORIES=Path('/var/lib/geteverything-categories')
TRAINER='geteverything-product-trainer'
EVALUATOR='geteverything-product-lora-eval'


def run(args,timeout=30):
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise RuntimeError(args[0]+' failed: '+result.stderr[-700:])
    return result.stdout.strip()


def atomic(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2));temporary.replace(path)


def lease(active):
    atomic(CATEGORIES/'state/product-training.json',{'at':time.time(),'active':active})


def state(name):
    result=subprocess.run(['docker','container','inspect','--format','{{json .State}}',name],capture_output=True,text=True,timeout=20)
    return json.loads(result.stdout) if result.returncode==0 else None


def cleanup(name):
    previous=state(name)
    if previous is None:return
    if previous['Running']:raise RuntimeError('A training container is already running')
    log=subprocess.run(['docker','logs','--tail','100',name],capture_output=True,text=True,timeout=20)
    (ROOT/(name+'-last.log')).write_text(log.stdout+log.stderr)
    run(['docker','rm',name])


def publish(value):
    safe={k:v for k,v in value.items() if k not in ('adapter','weights','files')}
    code=('from gadmin.categories.worker import setup;setup();'
          'import json;from gadmin.deals.models import ClassificationState;'
          'ClassificationState.objects.update_or_create(key="products:llm_training",defaults={"value":json.loads('+repr(json.dumps(safe))+')})')
    run(['docker','exec','geteverything-category-worker','python','-c',code])


def resources():
    ticks=[int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    available=next(int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
    return sum(ticks),ticks[3]+ticks[4],available


def pressure_action(cpu,available,busy):
    if available<3*1024**3:return 'stop'
    if cpu>=80 and busy>=2:return 'pause'
    if cpu<65:return 'resume'
    return 'keep'


def training_policy(config):
    policy={'epochs':4,'max_steps':1200,'rank':16,'learning_rate':8e-5,
            'cpu':0.35,'evaluation_cpu':0.35,'training_hours':18,'evaluation_hours':4}
    policy.update(config.get('training',{}))
    assert 1<=policy['epochs']<=8 and 1<=policy['max_steps']<=2000
    assert policy['rank'] in (8,16,32) and 1e-6<=policy['learning_rate']<=5e-4
    assert 0.1<=policy['cpu']<=0.5 and 0.1<=policy['evaluation_cpu']<=0.5
    assert 1<=policy['training_hours']<=18 and 1<=policy['evaluation_hours']<=4
    return policy


def prune_cache(root,limit=4*1024**3):
    files=sorted((root/'frozen-cache').glob('*.pt'),key=lambda p:p.stat().st_mtime)
    total=sum(p.stat().st_size for p in files)
    for path in files:
        stat=path.stat()
        if stat.st_nlink==1 and (total>limit or time.time()-stat.st_mtime>7*86400):
            path.unlink();total-=stat.st_size


def validate_import(trained,data,checkpoint,root):
    assert trained['status']=='trained_awaiting_generation_eval' and trained['probe'] is False
    assert trained['promoted'] is False
    assert trained['base_revision']==checkpoint['revision'], 'Imported base model differs from server'
    payload={key:value for key,value in data.items() if key!='sha256'}
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    assert trained['dataset_sha256']==data['sha256']==digest, 'Imported dataset checksum mismatch'
    assert trained['prompt_version']==data['version'], 'Imported prompt version mismatch'
    expected=hashlib.sha256((digest+checkpoint['revision']+data['version']+
                            json.dumps(trained['recipe'],sort_keys=True)).encode()).hexdigest()[:20]
    assert trained['run_id']==expected, 'Imported run identity mismatch'
    assert trained['training_examples']==len(data['train']) and trained['validation_examples']==len(data['validation'])
    assert 0<trained['best_step']<=trained['step']<=min(trained['recipe']['max_steps'],trained['recipe']['epochs']*len(data['train']))
    for field in ('baseline_validation_loss','final_validation_loss','lora_b_squared_norm'):
        assert math.isfinite(trained[field]) and trained[field]>0, 'Invalid imported training result'
    work=root/'runs'/expected
    assert trained['adapter']=='/training/runs/'+expected+'/best', 'Imported adapter path mismatch'
    assert hashlib.sha256((work/'best/adapter_model.safetensors').read_bytes()).hexdigest()==trained['adapter_sha256'], 'Imported adapter checksum mismatch'
    assert (work/'best/adapter_config.json').is_file(), 'Imported adapter configuration missing'


def wait(name,seconds):
    started=time.monotonic();previous=resources();busy=0;last_publish=0
    while time.monotonic()-started<seconds:
        info=state(name)
        if not info or not info['Running']:
            if not info or info['ExitCode'] or info['OOMKilled']:raise RuntimeError('Training stage failed; inspect bounded container log')
            return
        lease(True)
        current=resources();delta=current[0]-previous[0]
        cpu=100*(1-(current[1]-previous[1])/delta) if delta>0 else 0
        previous=current;busy=busy+1 if cpu>=80 else 0
        action=pressure_action(cpu,current[2],busy)
        for target in (TRAINER,EVALUATOR):
            status=state(target)
            if not status or not status['Running']:continue
            if action=='stop':
                if status['Paused']:run(['docker','unpause',target])
                run(['docker','stop','--time','45',target],60)
            elif action=='pause' and not status['Paused']:run(['docker','pause',target])
            elif action=='resume' and status['Paused']:run(['docker','unpause',target])
        if action=='stop':raise RuntimeError('Training paused for crawler memory headroom')
        if time.monotonic()-last_publish>60 and (ROOT/'status.json').exists():
            progress=json.loads((ROOT/'status.json').read_text())
            progress.update(host_cpu_percent=round(cpu,1),memory_available=current[2],resource_action=action)
            publish(progress);last_publish=time.monotonic()
        time.sleep(10)
    raise RuntimeError('Training stage exceeded time budget')


def command(config,command,network='none',memory='6g',cpu='0.20'):
    cleanup(TRAINER)
    run(['docker','run','-d','--name',TRAINER,'--init','--network='+network,'--read-only',
         '--cap-drop=ALL','--security-opt=no-new-privileges','--memory='+memory,'--memory-swap='+memory,
         '--cpus='+cpu,'--cpu-shares=32','--pids-limit=64','--oom-score-adj=800',
         '--tmpfs=/tmp:rw,nosuid,nodev,size=64m','--log-driver=local','--log-opt=max-size=2m','--log-opt=max-file=2',
         '--mount=type=bind,src='+str(ROOT)+',dst=/training',
         '--mount=type=bind,src='+str(SOURCE)+',dst=/training-code,readonly',
         '--mount=type=bind,src='+str(SOURCE/'products')+',dst=/app/gadmin/products,readonly',
         '--mount=type=bind,src='+str(SOURCE/'categories')+',dst=/app/gadmin/categories,readonly',
         '--mount=type=bind,src='+str(SOURCE/'metrics')+',dst=/app/gadmin/metrics,readonly',
         config['image'],*command])


def promote(result,config):
    if result.get('status')!='validated' or result.get('gate',{}).get('passed') is not True:
        return False
    deployed_version=run(['docker','exec','geteverything-category-worker','python','-c',
                         'from gadmin.products.sft import VERSION;print(VERSION)'])
    assert deployed_version==result['prompt_version'], 'Worker prompt changed during training'
    from_source=ROOT/'runs'/result['run_id']/'adapter.gguf'
    digest=hashlib.sha256(from_source.read_bytes()).hexdigest()
    assert digest==result['gguf_sha256']
    runtime_path=Path('/etc/geteverything-categories/runtime.json')
    previous=json.loads(runtime_path.read_text())
    model=Path(previous['model_file'])
    assert model.name=='Qwen3.5-2B-Q4_K_M.gguf'
    target=CATEGORIES/'models/adapters'/(digest+'.gguf')
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(from_source,target);target.chmod(0o644)
    atomic(ROOT/'runtime-before-promotion.json',previous)
    marker=CATEGORIES/'state/product-adapter.json'
    old_marker=json.loads(marker.read_text()) if marker.exists() else {'enabled':False}
    try:
        atomic(runtime_path,previous|{'product_lora_file':str(target),'product_lora_sha256':digest})
        old=state('geteverything-category-model')
        if old and old['Running']:run(['docker','stop','--time','10','geteverything-category-model'])
        if old:run(['docker','rm','geteverything-category-model'])
        lease(False)
        # The resource guard still controls startup after promotion.
        for _ in range(3):
            run(['python3','/usr/local/lib/geteverything-categories/guard.py'])
            time.sleep(20)
        # This binary reports initial adapter scale 1 even with init-without-apply.
        # Explicitly disable the default; product requests opt in individually.
        disable=urllib.request.Request('http://127.0.0.1:8094/lora-adapters',data=b'[]',
                                       headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(disable,timeout=20) as response:assert response.status==200
        with urllib.request.urlopen('http://127.0.0.1:8094/lora-adapters',timeout=20) as response:adapters=json.load(response)
        assert any(row.get('id')==0 and row.get('scale')==0 for row in adapters)
        atomic(marker,{'enabled':True,'adapter_id':0,'sha256':digest,
                       'prompt_version':result['prompt_version'],'run_id':result['run_id']})
        marker.chmod(0o644)
        result.update(status='promoted',promoted=True,promoted_at=time.time())
        result['at']=time.time()
        atomic(ROOT/'active.json',result);atomic(ROOT/'status.json',result);publish(result)
        return True
    except Exception:
        atomic(marker,old_marker);marker.chmod(0o644)
        atomic(runtime_path,previous)
        old=state('geteverything-category-model')
        if old and old['Running']:run(['docker','stop','--time','10','geteverything-category-model'])
        if old:run(['docker','rm','geteverything-category-model'])
        raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--force',action='store_true')
    parser.add_argument('--evaluate-only',action='store_true',
                        help='Evaluate a completed local training run already imported into ROOT')
    args=parser.parse_args()
    os.umask(0o077)
    def interrupt(*_):raise InterruptedError('Training controller stopped; checkpoints retained')
    signal.signal(signal.SIGTERM,interrupt)
    signal.signal(signal.SIGINT,interrupt)
    ROOT.mkdir(parents=True,exist_ok=True)
    config=json.loads(Path('/etc/geteverything-product-training.json').read_text())
    policy=training_policy(config)
    with Path('/run/geteverything-product-training.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        active=json.loads((ROOT/'active.json').read_text()).get('run_id') if (ROOT/'active.json').exists() else None
        finished=sorted([p for p in (ROOT/'runs').glob('*') if p.is_dir() and not p.is_symlink() and
                         (p/'result.json').is_file()],key=lambda p:p.stat().st_mtime,reverse=True)
        for old in finished[2:]:
            if old.name!=active and len(old.name) in (20,26):shutil.rmtree(old)
        prune_cache(ROOT)
        if shutil.disk_usage(ROOT).free<5*1024**3:raise RuntimeError('Training requires 5 GiB free disk')
        data_path=ROOT/'dataset.json'
        if args.evaluate_only:
            data=json.loads(data_path.read_text())
            trained=json.loads((ROOT/'status.json').read_text())
            validate_import(trained,data,json.loads((ROOT/'downloaded.json').read_text()),ROOT)
        else:
            temporary='/tmp/product-sft-'+str(time.time_ns())+'.json'
            run(['docker','exec','geteverything-category-worker','python','-m','gadmin.products.manage','sft-export','--output',temporary])
            # Docker's archive API does not see this worker's tmpfs. Read within its mount namespace.
            try:
                data=json.loads(run(['docker','exec','geteverything-category-worker','cat',temporary]))
                atomic(data_path,data);data_path.chmod(0o600)
            finally:
                run(['docker','exec','geteverything-category-worker','rm','-f',temporary])
        previous=json.loads((ROOT/'attempt.json').read_text()) if (ROOT/'attempt.json').exists() else {}
        policy_sha=hashlib.sha256(json.dumps({'policy':policy,'image':config['image'],
            'trainer_sha256':hashlib.sha256((SOURCE/'train.py').read_bytes()).hexdigest()},sort_keys=True).encode()).hexdigest()
        curriculum_sha=hashlib.sha256(json.dumps([r for r in data['train']+data['validation']
            if r['origin']=='bootstrap_review'],sort_keys=True).encode()).hexdigest()
        same=previous.get('dataset_sha256')==data['sha256'] and previous.get('policy_sha256')==policy_sha
        if not args.evaluate_only and same and (previous.get('complete') or previous.get('attempts',0)>=3):return
        operator_count=sum(r['origin']=='operator' for r in data['train']+data['validation'])
        if (not args.evaluate_only and not args.force and previous.get('complete') and previous.get('policy_sha256')==policy_sha
                and previous.get('curriculum_sha256')==curriculum_sha
                and operator_count-previous.get('operator_count',0)<16):return
        attempt={'at':time.time(),'dataset_sha256':data['sha256'],'operator_count':operator_count,
                 'attempts':previous.get('attempts',0)+1 if same else 1,'complete':False,
                 'policy_sha256':policy_sha,'curriculum_sha256':curriculum_sha,'policy':policy}
        atomic(ROOT/'attempt.json',attempt)
        try:
            lease(True)
            run(['python3','/usr/local/lib/geteverything-categories/guard.py'])
            if not args.evaluate_only:
                starting={'status':'starting','at':time.time(),'probe':False,'dataset_sha256':data['sha256'],
                          'training_examples':len(data['train']),'validation_examples':len(data['validation'])}
                atomic(ROOT/'status.json',starting);publish(starting)
                command(config,['python','/training-code/train.py','--dataset','/training/dataset.json',
                                '--epochs',str(policy['epochs']),'--max-steps',str(policy['max_steps']),
                                '--rank',str(policy['rank']),'--learning-rate',str(policy['learning_rate'])],cpu=str(policy['cpu']))
                wait(TRAINER,policy['training_hours']*3600)
            trained=json.loads((ROOT/'status.json').read_text());publish(trained)
            assert trained['status']=='trained_awaiting_generation_eval' and trained['probe'] is False
            work='/training/runs/'+trained['run_id']
            assert trained['adapter'] in (work+'/best',work+'/checkpoint')
            command(config,['python','/training/tools/convert_lora_to_gguf.py','--base','/training/base',
                            '--outfile',work+'/adapter.gguf',trained['adapter']],memory='1g')
            wait(TRAINER,600)
            runtime=json.loads(Path('/etc/geteverything-categories/runtime.json').read_text())
            cleanup(EVALUATOR)
            previous_mount=[];previous_args=[];evaluation_args=[]
            if runtime.get('product_lora_file'):
                previous_mount=['--mount=type=bind,src='+runtime['product_lora_file']+',dst=/models/previous.gguf,readonly']
                previous_args=['--lora','/models/previous.gguf']
                evaluation_args=['--baseline-adapter','1']
            run(['docker','run','-d','--name',EVALUATOR,'--init','--network=host','--read-only',
                 '--cap-drop=ALL','--security-opt=no-new-privileges','--cpus='+str(policy['evaluation_cpu']),
                 '--memory=3g','--memory-swap=3g','--no-healthcheck',
                 '--pids-limit=64','--oom-score-adj=800','--tmpfs=/tmp:rw,nosuid,nodev,size=32m',
                 '--log-driver=local','--log-opt=max-size=2m','--log-opt=max-file=2',
                 '--mount=type=bind,src='+runtime['model_file']+',dst=/models/base.gguf,readonly',
                 '--mount=type=bind,src='+str(ROOT/'runs'/trained['run_id']/'adapter.gguf')+',dst=/models/adapter.gguf,readonly',
                 *previous_mount,
                 runtime['model_image'],'-m','/models/base.gguf','--lora','/models/adapter.gguf',*previous_args,'--lora-init-without-apply',
                 '--host','127.0.0.1','--port','8095','--alias','category-local','--threads','1','--threads-batch','1',
                 '--ctx-size','2048','--parallel','1','--batch-size','256','--ubatch-size','64','--poll','0','--poll-batch','0','--jinja','--no-webui'])
            for retry in range(3):
                lease(True);time.sleep(20)
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8095/health',timeout=10) as response:assert response.status==200
                    break
                except (OSError,AssertionError):
                    if retry==2:raise
            command(config,['python','/training-code/evaluate.py','--dataset','/training/dataset.json',*evaluation_args],network='host',memory='192m',cpu='0.05')
            wait(TRAINER,policy['evaluation_hours']*3600)
            run(['docker','stop','--time','10',EVALUATOR])
            result=json.loads((ROOT/'evaluation.json').read_text());publish(result)
            promote(result,config)
            attempt.update(complete=True,result=result['status']);atomic(ROOT/'attempt.json',attempt)
        finally:
            for name in (TRAINER,EVALUATOR):
                info=state(name)
                if info and info['Running']:
                    if info['Paused']:run(['docker','unpause',name])
                    run(['docker','stop','--time','45',name],60)
            lease(False)


if __name__=='__main__':
    try:main()
    except BlockingIOError:pass
    except Exception as error:
        value={'status':'failed','at':time.time(),'reason':str(error)[:300]}
        atomic(ROOT/'runner-error.json',value)
        progress=json.loads((ROOT/'status.json').read_text()) if (ROOT/'status.json').exists() else {}
        atomic(ROOT/'status.json',progress|value)
        try:publish(value)
        except Exception:pass
        raise
