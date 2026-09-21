#!/usr/bin/env python3
"""Evaluate on the server's loopback llama.cpp endpoint; never send titles outside."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from gadmin.categories.llm import LocalModel, InvalidResult, Unavailable
from gadmin.categories import llm, rules, taxonomy, vocabulary
from gadmin.metrics import parser as metrics_parser
from gadmin.categories.taxonomy import GROUPS
from gadmin.products.local_model import SYSTEM as BASE_SYSTEM, repair_output
from gadmin.products.sft import SYSTEM, VERSION, split_audit, model_title
from gadmin.products.sft_validation import score, promotion_gate, pair_scores
from gadmin.products import identity, local_model, sft, sft_validation


def evaluation_context(root, state, data, baseline_adapter, endpoint):
    adapter=root/'runs'/state['run_id']/'adapter.gguf'
    protocol=hashlib.sha256(b''.join(Path(path).read_bytes() for path in
        (__file__,llm.__file__,rules.__file__,taxonomy.__file__,vocabulary.__file__,metrics_parser.__file__,
         identity.__file__,local_model.__file__,sft.__file__,sft_validation.__file__))).hexdigest()
    return {'version':'generation-eval-4','run_id':state['run_id'],
            'dataset_sha256':data['sha256'],'prompt_version':VERSION,
            'adapter_sha256':hashlib.sha256(adapter.read_bytes()).hexdigest(),
            'protocol_sha256':protocol,
            'baseline_prompt_sha256':hashlib.sha256((SYSTEM if baseline_adapter is not None else BASE_SYSTEM).encode()).hexdigest(),
            'candidate_prompt_sha256':hashlib.sha256(SYSTEM.encode()).hexdigest(),
            'baseline_adapter':baseline_adapter,'endpoint':endpoint}


def resume_details(work, context, validation):
    partial=work/'generation-progress.json';marker=work/'generation-context.json'
    if partial.exists():
        if not marker.exists() or json.loads(marker.read_text())!=context:
            raise RuntimeError('Evaluation context changed; archive partial results before retrying')
        details=json.loads(partial.read_text())
        expected=[(mode,row) for mode in ('baseline','same_prompt_base','candidate') for row in validation]
        assert len(details)<=len(expected)
        for actual,(mode,row) in zip(details,expected):
            assert actual['mode']==mode and actual['title']==row['title'] and actual['expected']==row['target']
        return details
    temporary=marker.with_suffix('.tmp');temporary.write_text(json.dumps(context,indent=2));temporary.replace(marker)
    return []


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=Path('/training'))
    parser.add_argument('--endpoint',default='http://127.0.0.1:8095')
    parser.add_argument('--baseline-adapter',type=int,choices=[1])
    args=parser.parse_args()
    state=json.loads((args.root/'status.json').read_text())
    assert state['status'] in ('trained_awaiting_generation_eval','evaluating') and state['probe'] is False
    data=json.loads(args.dataset.read_text())
    assert data['sha256']==state['dataset_sha256']
    assert state.get('prompt_version')==data['version']==VERSION, 'Training/evaluation prompt mismatch'
    model=LocalModel(endpoint=args.endpoint,timeout=240)
    properties={key:{'type':'string','maxLength':160} for key in ('brand','name','model','variant')}
    properties.update(is_product={'type':'boolean'},category={'type':'string','enum':[*GROUPS,'unknown']})
    schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    summaries={}
    work=args.root/'runs'/state['run_id']
    partial=work/'generation-progress.json'
    context=evaluation_context(args.root,state,data,args.baseline_adapter,args.endpoint)
    details=resume_details(work,context,data['validation'])
    def progress(**values):
        current={**state,'status':'evaluating','at':time.time(),
                 'evaluation_completed':len(details),'evaluation_total':3*len(data['validation']),**values}
        temporary=(args.root/'status.json').with_suffix('.tmp')
        temporary.write_text(json.dumps(current,indent=2));temporary.replace(args.root/'status.json')
    progress(evaluation_mode='baseline')
    baseline_system=SYSTEM if args.baseline_adapter is not None else BASE_SYSTEM
    for mode,system,adapter in [('baseline',baseline_system,args.baseline_adapter),
                                ('same_prompt_base',SYSTEM,None),('candidate',SYSTEM,0)]:
        progress(evaluation_mode=mode)
        previous=[row for row in details if row['mode']==mode]
        outcomes=[{key:row[key] for key in ('correct','valid','false_merge')} for row in previous]
        times=[row['seconds'] for row in previous]
        normalized=mode!='baseline' or args.baseline_adapter is not None
        input_title=lambda row:model_title(row['title']) if normalized else row['title']
        cached={input_title(row):(row['generated'],row['seconds']) for row in previous if row.get('generated')}
        for row in data['validation'][len(previous):]:
            start=time.monotonic()
            title=input_title(row)
            reused=title in cached
            try:
                if reused:
                    generated,elapsed=cached[title]
                else:
                    generated=model.structured(system,{'title':title},schema,224,adapter=adapter)
                    elapsed=round(time.monotonic()-start,3)
                    if generated:cached[title]=(generated,elapsed)
                raw=repair_output(row['title'],generated)
                outcome=score(row['title'],row['target'],raw)
            except (InvalidResult,Unavailable):
                generated={};raw={};outcome={'correct':False,'valid':False,'false_merge':False}
                elapsed=round(time.monotonic()-start,3)
            outcomes.append(outcome);times.append(elapsed)
            details.append({'mode':mode,'family':row['family'],'title':row['title'],
                            'generated':generated,'actual':raw,'expected':row['target'],'seconds':elapsed,
                            'inference_reused':reused,**outcome})
            temporary=partial.with_suffix('.tmp')
            temporary.write_text(json.dumps(details,ensure_ascii=False,indent=2));temporary.replace(partial)
            progress(evaluation_mode=mode)
            print(json.dumps({'mode':mode,'completed':len(outcomes),'total':len(data['validation']),**outcome}),flush=True)
        summaries[mode]={key:sum(row[key] for row in outcomes) for key in ('correct','valid','false_merge')}
        summaries[mode]['p95_seconds']=sorted(times)[min(len(times)-1,int(len(times)*.95))]
        summaries[mode]['pairs']=pair_scores([row for row in details if row['mode']==mode])
    baseline={row['title']:row for row in details if row['mode']=='baseline'}
    same_prompt={row['title']:row for row in details if row['mode']=='same_prompt_base'}
    result={**state,**summaries,'split_audit':split_audit(data),'validation_count':len(data['validation']),
            'validation_families':len({row['family'] for row in data['validation']}),
            'validation_negatives':sum(not row['target']['is_product'] for row in data['validation']),
            'evaluation_completed':len(details),'evaluation_total':3*len(data['validation']),
            'inference_requests':sum(not row.get('inference_reused',False) for row in details),
            'baseline_adapter_id':args.baseline_adapter,
            'regressions':sum(row['mode']=='candidate' and baseline[row['title']]['correct'] and not row['correct'] for row in details),
            'same_prompt_regressions':sum(row['mode']=='candidate' and same_prompt[row['title']]['correct'] and not row['correct'] for row in details),
            'gguf_sha256':hashlib.sha256((work/'adapter.gguf').read_bytes()).hexdigest(),'evaluated_at':time.time()}
    result['gate']=promotion_gate(result)
    result['status']='validated' if result['gate']['passed'] else 'rejected'
    result['at']=time.time()
    for target in (work/'evaluation.json',args.root/'evaluation.json',args.root/'status.json'):
        temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(result,indent=2));temporary.replace(target)
    print(json.dumps({'status':result['status'],'gate':result['gate'],'baseline':summaries['baseline'],'candidate':summaries['candidate']}),flush=True)


if __name__=='__main__':main()
