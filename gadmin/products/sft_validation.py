"""Promotion requires improvement on held-out product families without regressions."""
from .identity import grounded, signature
from .sft import valid_target


def pair_scores(details):
    """Check the identity decision across independent held-out titles, not just fields."""
    rows = []
    for row in details:
        wanted, _ = grounded(row['title'], row['expected'])
        if wanted is None:
            continue
        actual, _ = grounded(row['title'], row['actual']) if row['valid'] else (None, '')
        rows.append((signature(wanted), signature(actual) if actual else None))
    result = dict(same_pairs=0, different_pairs=0, false_merges=0, false_splits=0)
    for index, (wanted, actual) in enumerate(rows):
        for other_wanted, other_actual in rows[index+1:]:
            same = wanted == other_wanted
            connected = actual is not None and actual == other_actual
            result['same_pairs' if same else 'different_pairs'] += 1
            result['false_merges'] += bool(not same and connected)
            result['false_splits'] += bool(same and not connected)
    return result


def score(title, expected, actual):
    schema=valid_target(title, actual)
    false_merge=bool(actual.get('is_product') is True and expected['is_product'] is False)
    if not schema:
        return {'correct':False,'valid':False,'false_merge':false_merge}
    if not expected['is_product']:
        return {'correct':actual['is_product'] is False,'valid':True,'false_merge':false_merge}
    parsed,_=grounded(title,actual)
    wanted,_=grounded(title,expected)
    return {'correct':bool(parsed and wanted and signature(parsed)==signature(wanted) and
                           actual['category']==expected['category']),
            'valid':True,'false_merge':False}


def promotion_gate(result):
    baseline=result['baseline'];candidate=result['candidate']
    conditions={
        'full_training':not result.get('probe',True),
        'heldout_count':result.get('validation_count',0)>=40,
        'heldout_diversity':result.get('validation_families',0)>=12 and result.get('validation_negatives',0)>=8,
        'weights_changed':result.get('lora_b_squared_norm',0)>0,
        'validation_loss_improved':result.get('loss_gate') is True,
        'generation_improved':candidate['correct']>baseline['correct'],
        'accuracy_floor':candidate['correct']>=0.8*result.get('validation_count',0),
        'no_regressions':result.get('regressions',1)==0,
        'no_false_merges':candidate['false_merge']==0,
        'identity_pairs':candidate.get('pairs',{}).get('same_pairs',0)>=10 and candidate.get('pairs',{}).get('different_pairs',0)>=20,
        'no_pair_false_merges':candidate.get('pairs',{}).get('false_merges',1)==0,
        'no_pair_recall_regression':candidate.get('pairs',{}).get('false_splits',1)<=baseline.get('pairs',{}).get('false_splits',0),
        'valid_outputs':candidate['valid']==result.get('validation_count'),
        'latency_budget':candidate['p95_seconds']<=max(90,baseline['p95_seconds']*1.25+10),
    }
    return {'passed':all(conditions.values()),'checks':conditions}
