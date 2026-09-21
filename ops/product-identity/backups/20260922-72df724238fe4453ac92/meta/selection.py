"""Select an already trained final checkpoint; do not claim additional training."""
import hashlib
import json
from pathlib import Path
import shutil
import time
from safetensors.torch import load_file

source=Path(__file__).resolve().parent
parent=json.loads((source/'runs/37f8e4b7f3556e079055/result.json').read_text())
old=source/'runs'/parent['run_id']
assert parent['step']==1800 and parent['best_step']==1164
checkpoint=old/'checkpoint'
weights=checkpoint/'adapter_model.safetensors'
digest=hashlib.sha256(weights.read_bytes()).hexdigest()
assert digest=='867001db5dc5e37f47b5df666946e072851c9f9b91bec4036df207a46dc62c71'
norm=sum(float(value.float().square().sum()) for name,value in load_file(str(weights)).items() if 'lora_B' in name)
recipe=parent['recipe']|{'checkpoint_selection':'final'}
run_id=hashlib.sha256((parent['dataset_sha256']+parent['base_revision']+parent['prompt_version']+
    json.dumps(recipe,sort_keys=True)).encode()).hexdigest()[:20]
root=source.with_name('product-training-v6-final')
root.mkdir(exist_ok=False)
work=root/'runs'/run_id
work.mkdir(parents=True)
for name in ('dataset.json','downloaded.json'):
    shutil.copy2(source/name,root/name)
(root/'base').symlink_to((source/'base').resolve(),target_is_directory=True)
shutil.copytree(checkpoint,work/'checkpoint')
shutil.copytree(checkpoint,work/'best',ignore=shutil.ignore_patterns('optimizer.pt'))
shutil.copy2(source/'cpu-diagnostic/last-checkpoint.gguf',work/'adapter.gguf')
assert hashlib.sha256((work/'adapter.gguf').read_bytes()).hexdigest()=='9ec27564330bddc935ef77edffcb7a13033cdbdc8085d5082ad605bfc4ca9035'
state=parent|{'run_id':run_id,'recipe':recipe,'selection_parent_run_id':parent['run_id'],
    'selection_at':time.time(),'selection_reason':'Final checkpoint passed the server CPU regression probe',
    'selection_additional_training_steps':0,'training_min_validation_loss':parent['best_validation_loss'],
    'training_min_validation_step':parent['best_step'],'best_step':parent['step'],
    'best_validation_loss':parent['validation_loss'],'final_validation_loss':parent['validation_loss'],
    'lora_b_squared_norm':norm,'adapter':str(work/'best'),'adapter_sha256':digest,
    'loss_gate':parent['validation_loss']<parent['baseline_validation_loss'],
    'status':'trained_awaiting_generation_eval','promoted':False,'at':time.time()}
for path in (root/'status.json',work/'result.json'):
    path.write_text(json.dumps(state,indent=2))
shutil.copy2(source/'cpu-diagnostic/last_1.json',work/'local-cpu-generation.json')
shutil.copy2(Path(__file__),work/'selection.py')
print(json.dumps({'root':str(root),'run_id':run_id,'selected_step':state['best_step'],
    'additional_training_steps':0,'validation_loss':state['final_validation_loss'],
    'lora_b_squared_norm':norm,'adapter_sha256':digest}))
