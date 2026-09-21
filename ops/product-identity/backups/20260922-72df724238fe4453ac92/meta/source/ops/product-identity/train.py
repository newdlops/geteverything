#!/usr/bin/env python3
"""CPU LoRA on Qwen's final block, with reusable frozen-prefix activations."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
import shutil
import time

STOP = False
STATUS_PATH = None
TARGETS = ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']


def learning_rate(step, total, maximum):
    warmup = min(20, max(1, total // 20))
    if step < warmup:
        return maximum * (step + 1) / warmup
    progress = (step - warmup) / max(1, total - warmup - 1)
    return maximum * (0.1 + 0.9 * (1 + math.cos(math.pi * min(1, progress))) / 2)


def cache_key(revision, layer, ids):
    value = ['fp32-prefix-1', revision, layer, ids]
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def interrupted(*_):
    global STOP
    STOP = True


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def install_cpu_kernels(model):
    import torch
    from types import MethodType
    def linear(module,value):
        return torch.nn.functional.linear(value.float(),module.weight.float(),
            module.bias.float() if module.bias is not None else None).to(value.dtype)
    def depthwise(module,value):
        padding=module.padding[0];kernel=module.kernel_size[0]
        padded=torch.nn.functional.pad(value.float(),(padding,padding))
        length=padded.shape[-1]-kernel+1
        result=torch.zeros((*value.shape[:-1],length),dtype=torch.float32,device=value.device)
        for offset in range(kernel):
            result=result+padded[...,offset:offset+length]*module.weight[:,0,offset].float()[None,:,None]
        if module.bias is not None:result=result+module.bias.float()[None,:,None]
        return result.to(value.dtype)
    def attention_forward(original):
        def forward(_module,hidden_states,*args,**kwargs):
            result=original(hidden_states.float(),*args,**kwargs)
            if isinstance(result,tuple):return (result[0].to(hidden_states.dtype),*result[1:])
            return result.to(hidden_states.dtype)
        return forward
    for module in model.modules():
        if isinstance(module,torch.nn.Linear):module.forward=MethodType(linear,module)
        elif (isinstance(module,torch.nn.Conv1d) and module.groups==module.in_channels==module.out_channels and
              module.stride==(1,) and module.dilation==(1,) and module.padding_mode=='zeros'):
            module.forward=MethodType(depthwise,module)
        elif type(module).__name__=='Qwen3_5Attention':
            module.forward=MethodType(attention_forward(module.forward),module)


def main():
    global STATUS_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/training'))
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=4)
    parser.add_argument('--max-steps', type=int, default=1200)
    parser.add_argument('--rank', type=int, choices=(8, 16, 32), default=16)
    parser.add_argument('--learning-rate', type=float, default=8e-5)
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    assert 1 <= args.epochs <= 8 and 1 <= args.max_steps <= 2000
    assert 1e-6 <= args.learning_rate <= 5e-4
    assert 1 <= args.threads <= 8
    STATUS_PATH = args.root/'status.json'
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer, Qwen3_5ForCausalLM, Qwen3_5TextConfig
    from gadmin.products.sft import SYSTEM, VERSION, dataset, model_title
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(42)
    torch.backends.cuda.matmul.allow_tf32 = False
    raw = json.loads(args.dataset.read_text())
    data = dataset(raw['train'] + raw['validation'])
    assert data['sha256'] == raw['sha256'], 'Dataset has changed'
    if args.probe:
        data['train'] = data['train'][:2]
        data['validation'] = data['validation'][:2]
    root = args.root
    checkpoint = json.loads((root/'downloaded.json').read_text())
    recipe={'version':'last-block-lora-fp32-3','rank':args.rank,'alpha':args.rank*2,
            'learning_rate':args.learning_rate,'targets':TARGETS,'scheduler':'warmup_cosine',
            'epochs':args.epochs,'max_steps':args.max_steps,'early_stopping_patience':2}
    run_id = hashlib.sha256((data['sha256']+checkpoint['revision']+VERSION+
                            json.dumps(recipe,sort_keys=True)).encode()).hexdigest()[:20]
    if args.probe:run_id += '-probe'
    work = root/'runs'/run_id
    cache = work/'cache'
    cache.mkdir(parents=True, exist_ok=True)
    shared_cache = root/'frozen-cache'
    shared_cache.mkdir(exist_ok=True)
    started = time.time()
    progress = {'run_id':run_id, 'dataset_sha256':data['sha256'], 'base_revision':checkpoint['revision'],
                'training_examples':len(data['train']), 'validation_examples':len(data['validation']),
                'started_at':started, 'step':0, 'promoted':False, 'probe':args.probe,'recipe':recipe,
                'prompt_version':VERSION,'cache_reused':0,
                'training_device':'cpu','cpu_threads':args.threads}
    def report(**values):
        progress.update(values, at=time.time())
        atomic_json(root/'status.json', progress)
        print(json.dumps(values), flush=True)
    report(status='loading_model')
    config = Qwen3_5TextConfig(**json.loads((root/'base/config.json').read_text())['text_config'])
    config.use_cache = False
    model, loading = Qwen3_5ForCausalLM.from_pretrained(str(root/'base'), config=config,
        dtype=torch.bfloat16, device_map='cpu', attn_implementation='eager', local_files_only=True,
        trust_remote_code=False, key_mapping={r'^model.language_model\.':'model.'},
        output_loading_info=True)
    missing = [key for key in loading.get('missing_keys', []) if key != 'lm_head.weight']
    assert not missing, 'Missing checkpoint tensors: '+repr(missing[:3])
    # Ampere A1 has no native BF16 matrix instructions. Keep compact frozen weights,
    # but cast one matrix at a time for the much faster FP32 CPU GEMM path.
    install_cpu_kernels(model)
    tokenizer = AutoTokenizer.from_pretrained(str(root/'base'), local_files_only=True, trust_remote_code=False)
    last = len(model.model.layers)-1
    assert config.layer_types[last] == 'full_attention'
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=args.rank*2, lora_dropout=0,
        target_modules=TARGETS, layers_to_transform=[last], layers_pattern='layers',
        bias='none', task_type='CAUSAL_LM'))
    trained = [(name, value) for name,value in model.named_parameters() if value.requires_grad]
    assert trained and all(f'.layers.{last}.' in name and 'lora_' in name for name,_ in trained)
    model.eval()
    base = model.get_base_model()
    layer, norm, head = base.model.layers[last], base.model.norm, base.lm_head
    rows = data['train'] + data['validation']
    class Captured(Exception):
        pass
    def capture(_module, positional, keywords):
        raise Captured((positional, keywords))
    hook = layer.register_forward_pre_hook(capture, with_kwargs=True)
    report(status='caching_frozen_layers', compute='fp32_gemm_bf16_storage',trainable_parameters=sum(v.numel() for _,v in trained),
           frozen_parameters=sum(v.numel() for v in model.parameters() if not v.requires_grad))
    try:
        for index,row in enumerate(rows):
            if STOP:
                report(status='paused', reason='resource_guard_or_shutdown')
                return
            path = cache/f'{index:05d}.pt'
            if path.exists():
                report(cached=index+1, total_cache=len(rows), cache_reused=progress['cache_reused']+1)
                continue
            prompt = tokenizer.apply_chat_template([
                {'role':'system','content':SYSTEM},
                {'role':'user','content':json.dumps({'title':model_title(row['title'])}, ensure_ascii=False)},
            ], tokenize=True, return_dict=False, add_generation_prompt=True, enable_thinking=False)
            answer = tokenizer.encode(json.dumps(row['target'],ensure_ascii=False,separators=(',',':')),
                                      add_special_tokens=False)+[tokenizer.eos_token_id]
            assert len(prompt)+len(answer) <= 768, 'Training title exceeds context budget'
            ids = torch.tensor([prompt+answer], dtype=torch.long)
            shared = shared_cache/(cache_key(checkpoint['revision'], last, prompt+answer)+'.pt')
            if shared.exists():
                os.link(shared, path)
                report(cached=index+1, total_cache=len(rows), cache_reused=progress['cache_reused']+1)
                continue
            if shutil.disk_usage(root).free < 3*1024**3:
                raise RuntimeError('Frozen cache requires 3 GiB of remaining disk headroom')
            before = time.monotonic()
            try:
                with torch.no_grad():
                    base.model(input_ids=ids, use_cache=False)
            except Captured as found:
                positional, keywords = found.args[0]
                entry = {'positional':positional, 'keywords':keywords,
                         'answer_start':len(prompt), 'labels':ids[:,len(prompt):]}
                temporary = shared.with_suffix('.tmp')
                torch.save(entry, temporary)
                temporary.replace(shared)
                os.link(shared, path)
            else:
                raise RuntimeError('Frozen-layer capture did not run')
            report(cached=index+1, total_cache=len(rows), last_cache_seconds=round(time.monotonic()-before,2))
    finally:
        hook.remove()
    # No backward graph or optimizer is built for the first 23 frozen layers.
    for index in range(last):
        base.model.layers[index] = torch.nn.Identity()
    import gc
    gc.collect()
    optimizer = torch.optim.AdamW([value for _,value in trained], lr=args.learning_rate, weight_decay=0.01)
    def loss_for(index):
        entry = torch.load(cache/f'{index:05d}.pt', map_location='cpu', weights_only=True)
        result = layer(*entry['positional'], **entry['keywords'])
        hidden = result[0] if isinstance(result, tuple) else result
        hidden = norm(hidden[:,entry['answer_start']-1:-1,:])
        logits = head(hidden).float()
        return torch.nn.functional.cross_entropy(logits.reshape(-1,logits.shape[-1]),entry['labels'].reshape(-1))
    def evaluate():
        with torch.no_grad():
            return sum(float(loss_for(i)) for i in range(len(data['train']),len(rows)))/len(data['validation'])
    baseline = evaluate()
    report(status='training', baseline_validation_loss=baseline)
    resume = work/'checkpoint'
    if not resume.exists() and (work/'checkpoint.old').exists():
        (work/'checkpoint.old').rename(resume)
    step = 0
    best_loss, best_step, bad_epochs = math.inf, 0, 0
    if (resume/'adapter_model.safetensors').exists():
        from peft import set_peft_model_state_dict
        from safetensors.torch import load_file
        set_peft_model_state_dict(model, load_file(str(resume/'adapter_model.safetensors')))
        saved = torch.load(resume/'optimizer.pt',map_location='cpu',weights_only=True)
        optimizer.load_state_dict(saved['optimizer'])
        step = saved['step']
        best_loss, best_step, bad_epochs = saved.get('best_loss',math.inf), saved.get('best_step',0), saved.get('bad_epochs',0)
        report(step=step, resumed_from_step=step)
    schedule = []
    for epoch in range(args.epochs):
        indices = list(range(len(data['train'])))
        random.Random(42+epoch).shuffle(indices)
        schedule.extend(indices)
    schedule = schedule[:args.max_steps]
    def save_checkpoint(best=False):
        destination = work/('best' if best else 'checkpoint')
        temporary = destination.with_suffix('.tmp')
        temporary.mkdir(exist_ok=True)
        model.save_pretrained(temporary,safe_serialization=True,save_embedding_layers=False)
        if not best:
            torch.save({'optimizer':optimizer.state_dict(),'step':step,'best_loss':best_loss,
                        'best_step':best_step,'bad_epochs':bad_epochs},temporary/'optimizer.pt')
        old = destination.with_suffix('.old')
        if old.exists():shutil.rmtree(old)
        if destination.exists():destination.rename(old)
        temporary.rename(destination)
        if old.exists():shutil.rmtree(old)
    for index in schedule[step:]:
        if STOP:
            save_checkpoint()
            report(status='paused', step=step, reason='resource_guard_or_shutdown')
            return
        optimizer.zero_grad(set_to_none=True)
        for group in optimizer.param_groups:
            group['lr'] = learning_rate(step, len(schedule), args.learning_rate)
        before = time.monotonic()
        loss = loss_for(index)
        if not torch.isfinite(loss):raise RuntimeError('Non-finite training loss')
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_([v for _,v in trained],1.0)
        if not torch.isfinite(gradient_norm):raise RuntimeError('Non-finite adapter gradient')
        optimizer.step()
        step += 1
        report(step=step,total_steps=len(schedule),loss=float(loss.detach()),
               learning_rate=optimizer.param_groups[0]['lr'],last_step_seconds=round(time.monotonic()-before,2))
        if step % len(data['train']) == 0 or step == len(schedule):
            current_loss = evaluate()
            if current_loss < best_loss - 1e-5:
                best_loss, best_step, bad_epochs = current_loss, step, 0
                save_checkpoint(best=True)
            else:
                bad_epochs += 1
            save_checkpoint()
            report(epoch=math.ceil(step/len(data['train'])),validation_loss=current_loss,
                   best_validation_loss=best_loss,best_step=best_step,bad_epochs=bad_epochs)
            if bad_epochs >= 2:
                report(early_stopped=True)
                break
        elif step % 4 == 0:
            save_checkpoint()
    best = work/'best'
    if not best.exists() and (work/'best.old').exists():
        (work/'best.old').rename(best)
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    set_peft_model_state_dict(model, load_file(str(best/'adapter_model.safetensors')))
    final = evaluate()
    delta = sum(float(value.detach().float().square().sum()) for name,value in trained if 'lora_B' in name)
    assert delta > 0 and math.isfinite(delta), 'LoRA weights did not change'
    report(status='probe_complete' if args.probe else 'trained_awaiting_generation_eval', final_validation_loss=final,
           lora_b_squared_norm=delta, adapter=str(best),best_step=best_step,
           adapter_sha256=hashlib.sha256((best/'adapter_model.safetensors').read_bytes()).hexdigest(),
           loss_gate=final < baseline, elapsed_seconds=round(time.time()-started,1))
    atomic_json(work/'result.json',progress)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # No model prompts, titles, credentials or entire configuration in logs.
        print(json.dumps({'status':'failed','error_type':type(error).__name__,'reason':str(error)[:300]}),flush=True)
        if STATUS_PATH and STATUS_PATH.exists():
            state=json.loads(STATUS_PATH.read_text())
            state.update(status='failed',at=time.time(),error_type=type(error).__name__,reason=str(error)[:300])
            atomic_json(STATUS_PATH,state)
        raise
