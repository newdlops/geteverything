"""Small CPU-trained pair matcher; model guesses never become training labels."""
import hashlib
import json
import math
import re
import time

from .identity import alias_title, facts

FEATURE_VERSION = 'pair-features-3'


def features(left, right):
    a, b = alias_title(left), alias_title(right)
    grams = lambda text: {text[i:i+3] for i in range(max(1,len(text)-2))}
    x,y = grams(a),grams(b)
    overlap = len(x & y)
    nums = lambda text: set(re.findall(r'\d+(?:\.\d+)?[a-z가-힣]*', text))
    nx,ny = nums(a),nums(b)
    return [1.0, float(a==b), overlap/max(1,len(x|y)), overlap/max(1,min(len(x),len(y))),
            min(len(a),len(b))/max(1,max(len(a),len(b))), float(nx==ny),
            len(nx&ny)/max(1,len(nx|ny)), float(facts(left)==facts(right)),
            float(bool(nx and ny and nx!=ny))]


def probability(weights, vector):
    z = max(-30, min(30, sum(w*x for w,x in zip(weights,vector))))
    return 1/(1+math.exp(-z))


def fit(examples, epochs=160):
    if len(examples)<12 or {bool(row['same_product']) for row in examples}!={False,True}:
        raise ValueError('At least 12 reviewed positive and negative pairs are required')
    samples = [(features(row['left_title'],row['right_title']),int(row['same_product'])) for row in examples]
    weights = [0.0]*len(samples[0][0])
    for _ in range(epochs):
        gradient = [0.0]*len(weights)
        for vector,label in samples:
            error = probability(weights,vector)-label
            for i,value in enumerate(vector):gradient[i]+=error*value
        weights = [w-0.8*(g/len(samples)+(0.002*w if i else 0)) for i,(w,g) in enumerate(zip(weights,gradient))]
    return weights


def train(examples):
    # Keep all variants of a reviewed target in one split.
    group = lambda row: hashlib.sha256(alias_title(row['right_title']).encode()).hexdigest()
    training = [row for row in examples if int(group(row)[:8],16)%5]
    validation = [row for row in examples if not int(group(row)[:8],16)%5]
    weights = fit(training)
    tp=fp=tn=fn=0
    for row in validation:
        predicted = probability(weights,features(row['left_title'],row['right_title']))>=0.95
        if predicted and row['same_product']:tp+=1
        elif predicted:fp+=1
        elif row['same_product']:fn+=1
        else:tn+=1
    metrics={'feature_version':FEATURE_VERSION,'training_count':len(training),'validation_count':len(validation),
             'true_positive':tp,'false_positive':fp,'true_negative':tn,'false_negative':fn,
             'precision':tp/(tp+fp) if tp+fp else None,
             'auto_match_enabled':False,'usage':'candidate_ranking',
             'note':'Exact identity and reviewed aliases can link automatically; learned scores rank candidates.'}
    return weights,metrics


def train_stored():
    from gadmin.deals.models import ProductMatchExample, ProductMatcherVersion, ClassificationState
    # Empty right titles carry reviewed LLM abstentions, not product-pair labels.
    rows=list(ProductMatchExample.objects.exclude(right_title='').order_by('-id').values(
        'left_title','right_title','same_product','origin')[:2000])
    digest=hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20]
    version=FEATURE_VERSION+'/'+digest
    existing=ProductMatcherVersion.objects.filter(pk=version).first()
    if existing:
        ClassificationState.objects.update_or_create(key='products:matcher',defaults={'value':{
            'version':version,'weights':existing.weights,'metrics':existing.metrics}})
        ClassificationState.objects.update_or_create(key='products:training',defaults={'value':{
            'at':time.time(),'status':'ready','version':version,'examples':len(rows)}})
        return version
    weights,metrics=train(rows)
    metrics['origins']={origin:sum(row['origin']==origin for row in rows) for origin in {row['origin'] for row in rows}}
    ProductMatcherVersion.objects.get_or_create(version=version,defaults={'weights':weights,'metrics':metrics,'example_count':len(rows)})
    ClassificationState.objects.update_or_create(key='products:matcher',defaults={'value':{'version':version,'weights':weights,'metrics':metrics}})
    ClassificationState.objects.update_or_create(key='products:training',defaults={'value':{
        'at':time.time(),'status':'ready','version':version,'examples':len(rows)}})
    return version
