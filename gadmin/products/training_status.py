"""Present a training attempt separately from its eventual production promotion."""
from datetime import datetime, timezone
import time


PHASES={
    'starting':'학습 시작 중',
    'loading_model':'모델 준비 중',
    'caching_frozen_layers':'전처리 중',
    'training':'가중치 학습 중',
    'trained_awaiting_generation_eval':'학습 완료 · 평가 준비',
    'evaluating':'기존 모델과 비교 평가 중',
    'validated':'검증 통과 · 운영 반영 대기',
    'promoted':'운영 반영 완료',
    'rejected':'검증 미통과',
    'paused':'자원 여유 대기 중',
    'failed':'학습 작업 중단',
    'probe_complete':'소량 시험 완료',
}
CHECKS={
    'full_training':'전체 학습', 'heldout_count':'검증 표본 수',
    'weights_changed':'가중치 변경', 'validation_loss_improved':'검증 손실 개선',
    'generation_improved':'상품 식별 개선', 'no_regressions':'기존 정답 유지',
    'no_false_merges':'잘못된 상품 연결 방지', 'valid_outputs':'응답 형식',
    'latency_budget':'응답 시간',
}


def summary(data, now=None):
    data=data if isinstance(data,dict) else {}
    phase=data.get('status','')
    def number(key):
        value=data.get(key,0)
        return max(0,value) if isinstance(value,int) and not isinstance(value,bool) else 0
    current,total,unit,label=0,0,'',''
    if phase=='caching_frozen_layers':
        current,total,unit,label=number('cached'),number('total_cache'),'건','전처리'
    elif phase=='training':
        current,total,unit,label=number('step'),number('total_steps'),'단계','가중치 학습'
    elif phase=='evaluating':
        current,total,unit,label=number('evaluation_completed'),number('evaluation_total'),'건','응답 비교'
    updated=None
    try:
        updated=datetime.fromtimestamp(float(data.get('observed_at',data.get('at'))),tz=timezone.utc)
    except (TypeError,ValueError,OverflowError,OSError):pass
    finished=phase in ('promoted','rejected','failed','probe_complete')
    label_text=PHASES.get(phase,'학습 상태 확인 필요' if data else '학습 기록 없음')
    if not finished and data.get('resource_action')=='pause':label_text='자원 여유 대기 중'
    stale=bool(updated and not finished and (time.time() if now is None else now)-updated.timestamp()>600)
    checks=(data.get('gate') or {}).get('checks',{})
    baseline=data.get('baseline') or {};candidate=data.get('candidate') or {}
    return {
        'recorded':bool(data),'phase':phase,'label':label_text,
        'current':min(current,total),'total':total,'unit':unit,'progress_label':label,
        'training_examples':number('training_examples'),'validation_examples':number('validation_examples'),
        'has_examples':'training_examples' in data and 'validation_examples' in data,
        'updated_at':updated,'stale':stale,'promoted':phase=='promoted' and data.get('promoted') is True,
        'probe':data.get('probe') is True or phase=='probe_complete',
        'failed_checks':[label for key,label in CHECKS.items() if checks.get(key) is False],
        'comparison':{'baseline':baseline.get('correct'),'candidate':candidate.get('correct'),'total':number('validation_count')}
            if 'correct' in baseline and 'correct' in candidate else None,
    }
