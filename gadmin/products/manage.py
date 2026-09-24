"""Run with the existing category worker's database settings and resource limits."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['status','audit','audit-record','batch','train','seed-examples','export','sft-export','repair','repair-unsafe','deduplicate','backfill-step','backfill-status'])
    parser.add_argument('--limit',type=int,default=50)
    parser.add_argument('--output')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup')
    parser.add_argument('--product-id',action='append',dest='product_ids',
                        help='Limit a repair preview/apply to these product UUIDs (repeatable).')
    args=parser.parse_args()
    from gadmin.categories.worker import setup
    setup()
    from django.db.models import Count
    from gadmin.deals.models import ClassificationState,DealProduct,Product,ProductMatchExample,ProductPrice
    from . import bootstrap,jobs,learning
    if args.command in ('audit','audit-record'):
        from .quality import audit, record
        summary=audit(example_limit=max(0,min(args.limit,50)))
        print(json.dumps(record(summary) if args.command=='audit-record' else summary,ensure_ascii=False))
    elif args.command in ('backfill-step','backfill-status'):
        from . import backfill
        if args.command=='backfill-step':
            backfill.maintenance(args.limit)
            jobs.process_rules(max(1,min(args.limit,200)))
        print(json.dumps(backfill.refresh_status(),ensure_ascii=False))
    elif args.command=='deduplicate':
        if args.apply and not args.backup:parser.error('--apply requires --backup')
        from .deduplicate import deduplicate
        print(json.dumps(deduplicate(apply=args.apply,backup=args.backup,product_ids=args.product_ids),ensure_ascii=False))
    elif args.command=='batch':
        limit=max(1,min(args.limit,200))
        jobs.backfill(limit);jobs.process_rules(limit);jobs.process_prices(limit);jobs.refill_model_queue()
    elif args.command=='seed-examples':print(json.dumps({'examples':bootstrap.install()}))
    elif args.command=='train':print(json.dumps({'version':learning.train_stored()}))
    elif args.command=='sft-export':
        if not args.output:parser.error('--output is required')
        from .sft import export_stored
        print(json.dumps(export_stored(Path(args.output))))
    elif args.command=='repair':
        from .repair import repair
        print(json.dumps(repair(max(1,min(args.limit,200))),ensure_ascii=False))
    elif args.command=='repair-unsafe':
        from .repair import repair_unsafe
        print(json.dumps(repair_unsafe(args.limit),ensure_ascii=False))
    elif args.command=='export':
        if not args.output:parser.error('--output is required; training data is not printed to logs')
        target=Path(args.output)
        with target.open('x',encoding='utf-8') as handle:
            target.chmod(0o600)
            for row in ProductMatchExample.objects.order_by('id').iterator(chunk_size=100):
                handle.write(json.dumps({'left_title':row.left_title,'right_title':row.right_title,
                    'same_product':row.same_product,'extraction':row.extraction,'origin':row.origin},ensure_ascii=False)+'\n')
        print(json.dumps({'exported':ProductMatchExample.objects.count(),'path':str(target)}))
    if args.command in ('status','batch'):
        print(json.dumps({'products':Product.objects.filter(is_active=True).count(),'retained_product_ids':Product.objects.count(),'prices':ProductPrice.objects.count(),
            'linked_prices':ProductPrice.objects.filter(product__isnull=False).count(),
            'counts':list(DealProduct.objects.values('status','source').annotate(count=Count('deal_id')).order_by('status','source')),
            'states':dict(ClassificationState.objects.filter(key__startswith='products:').values_list('key','value'))},ensure_ascii=False))


if __name__=='__main__':main()
