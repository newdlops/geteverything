#!/usr/bin/env python3
"""Evaluate on the server's loopback llama.cpp endpoint; never send titles outside."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from gadmin.categories.llm import LocalModel, InvalidResult, Unavailable
from gadmin.categories.taxonomy import GROUPS
from gadmin.products.local_model import SYSTEM as BASE_SYSTEM, repair_output
from gadmin.products.sft import SYSTEM, VERSION
from gadmin.products.sft_validation import score, promotion_gate, pair_scores


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=Path('/training'))
    parser.add_argument('--endpoint',default='http://127.0.0.1:8095')
    parser.add_argument('--baseline-adapter',type=int,choices=[1])
    args=parser.parse_args()
    state=json.loads((args.root/'status.json').read_text())
    assert state['status']=='trained_awaiting_generation_eval' and state['probe'] is False
    data=json.loads(args.dataset.read_text())
    assert data['sha256']==state['dataset_sha256']
    assert state.get('prompt_version')==data['version']==VERSION, 'Training/evaluation prompt mismatch'
    model=LocalModel(endpoint=args.endpoint,timeout=240)
    properties={key:{'type':'string','maxLength':160} for key in ('brand','name','model','variant')}
    properties.update(is_product={'type':'boolean'},category={'type':'string','enum':[*GROUPS,'unknown']})
    schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    summaries={};details=[]
    work=args.root/'runs'/state['run_id']
    partial=work/'generation-progress.json'
    def progress(**values):
        current={**state,'status':'evaluating','at':time.time(),
                 'evaluation_completed':len(details),'evaluation_total':2*len(data['validation']),**values}
        temporary=(args.root/'status.json').with_suffix('.tmp')
        temporary.write_text(json.dumps(current,indent=2));temporary.replace(args.root/'status.json')
    progress(evaluation_mode='baseline')
    baseline_system=SYSTEM if args.baseline_adapter is not None else BASE_SYSTEM
    for mode,system,adapter in [('baseline',baseline_system,args.baseline_adapter),('candidate',SYSTEM,0)]:
        progress(evaluation_mode=mode)
        outcomes=[];times=[]
        for row in data['validation']:
            start=time.monotonic()
            try:
                raw=model.structured(system,{'title':row['title']},schema,224,adapter=adapter)
                raw=repair_output(row['title'],raw)
                outcome=score(row['title'],row['target'],raw)
            except (InvalidResult,Unavailable):
                raw={};outcome={'correct':False,'valid':False,'false_merge':False}
            elapsed=round(time.monotonic()-start,3)
            outcomes.append(outcome);times.append(elapsed)
            details.append({'mode':mode,'family':row['family'],'title':row['title'],
                            'actual':raw,'expected':row['target'],'seconds':elapsed,**outcome})
            temporary=partial.with_suffix('.tmp')
            temporary.write_text(json.dumps(details,ensure_ascii=False,indent=2));temporary.replace(partial)
            progress(evaluation_mode=mode)
            print(json.dumps({'mode':mode,'completed':len(outcomes),'total':len(data['validation']),**outcome}),flush=True)
        summaries[mode]={key:sum(row[key] for row in outcomes) for key in ('correct','valid','false_merge')}
        summaries[mode]['p95_seconds']=sorted(times)[min(len(times)-1,int(len(times)*.95))]
        summaries[mode]['pairs']=pair_scores([row for row in details if row['mode']==mode])
    baseline={row['title']:row for row in details if row['mode']=='baseline'}
    result={**state,**summaries,'validation_count':len(data['validation']),
            'validation_families':len({row['family'] for row in data['validation']}),
            'validation_negatives':sum(not row['target']['is_product'] for row in data['validation']),
            'evaluation_completed':len(details),'evaluation_total':2*len(data['validation']),
            'baseline_adapter_id':args.baseline_adapter,
            'regressions':sum(row['mode']=='candidate' and baseline[row['title']]['correct'] and not row['correct'] for row in details),
            'gguf_sha256':hashlib.sha256((work/'adapter.gguf').read_bytes()).hexdigest(),'evaluated_at':time.time()}
    result['gate']=promotion_gate(result)
    result['status']='validated' if result['gate']['passed'] else 'rejected'
    result['at']=time.time()
    for target in (work/'evaluation.json',args.root/'evaluation.json',args.root/'status.json'):
        temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(result,indent=2));temporary.replace(target)
    print(json.dumps({'status':result['status'],'gate':result['gate'],'baseline':summaries['baseline'],'candidate':summaries['candidate']}),flush=True)


if __name__=='__main__':main()
