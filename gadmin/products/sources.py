"""Durable, bounded collection of merchant IDs and conservative title-backed links."""
from datetime import timedelta
import hashlib
import json
import time

from django.db import transaction
from django.db.models import F
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from gadmin.deals.models import ClassificationState, Deal, DealProduct, ProductReference, ProductSource
from . import catalog, identifiers, identity

BACKFILL_KEY = 'products:sources:backfill:' + identifiers.VERSION


def snapshot(deal):
    return {'title': deal.subject or '', 'urls': [deal.shop_url_1 or '', deal.shop_url_2 or '']}


def seed(deal):
    return ProductSource.objects.get_or_create(deal=deal, defaults={'input': snapshot(deal)})[0]


def backfill(limit=50):
    limit = max(1, min(50, limit))
    with transaction.atomic():
        state, _ = ClassificationState.objects.select_for_update().get_or_create(key=BACKFILL_KEY, defaults={'value': {}})
        value = dict(state.value)
        if not value:
            ceiling = Deal.objects.order_by('-id').values_list('id', flat=True).first() or 0
            value = {'cursor': ceiling + 1, 'ceiling': ceiling, 'scanned': 0, 'started_at': time.time(), 'phase': 'scanning'}
        # Seed known products first so the unresolved backlog can reuse their IDs.
        known = list(Deal.objects.filter(product_source=None, product_assignment__status='ready')
                     .order_by('-id').only('id', 'subject', 'shop_url_1', 'shop_url_2')[:limit // 2])
        rows = []
        if value['phase'] == 'scanning':
            rows = list(Deal.objects.filter(id__lt=value['cursor']).order_by('-id')
                        .only('id', 'subject', 'shop_url_1', 'shop_url_2')[:limit])
            if rows:
                value.update(cursor=rows[-1].pk, scanned=value['scanned'] + len(rows))
            else:
                value['phase'] = 'scanned'
        unique = {deal.pk: deal for deal in [*known, *rows]}
        ProductSource.objects.bulk_create([ProductSource(deal=deal, input=snapshot(deal), priority=10) for deal in unique.values()],
                                         ignore_conflicts=True)
        value['at'] = time.time()
        state.value = value
        state.save(update_fields=['value'])
    return len(unique)


def references(payload):
    rows = {}
    for url in payload.get('urls', [])[:2]:
        for ref in identifiers.extract(url):
            rows[ref['key']] = {**ref, 'evidence': 'url'}
    return list(rows.values())


def persist(source, rows, *, status='ready', error='', attempts=None):
    with transaction.atomic():
        current = ProductSource.objects.select_for_update().filter(pk=source.pk, revision=source.revision, input=source.input).first()
        if current is None:
            return False
        ProductReference.objects.filter(source=current).delete()
        ProductReference.objects.bulk_create([ProductReference(source=current, **row) for row in {r['key']: r for r in rows}.values()])
        current.status = status
        current.last_error = error[:160]
        current.processed_at = timezone.now()
        if attempts is not None:
            current.attempts = attempts
        current.next_attempt_at = timezone.now() + timedelta(minutes=15 * current.attempts) if status == 'retry' else timezone.now()
        current.save()
    return True


def collect_pending(limit=50):
    rows = list(ProductSource.objects.filter(status='pending').order_by('priority', 'requested_at', 'pk')[:min(50, limit)])
    for source in rows:
        found = references(source.input)
        unresolved = any(identifiers.needs_redirect(url) for url in source.input.get('urls', [])[:2])
        status = 'ready' if found else 'retry' if unresolved else 'unresolved'
        if persist(source, found, status=status, error='' if found else 'redirect_pending' if unresolved else 'no_supported_product_id'):
            if found:
                try_link(source.pk)
    return len(rows)


def resolve_redirects_once(downloader=None):
    """At most one source per call, eight seconds overall, three attempts per input."""
    from django.db import close_old_connections
    from gadmin.thumbnails.fetch import ThumbnailError, fetch
    close_old_connections()
    try:
        source = ProductSource.objects.filter(status='retry', attempts__lt=3,
            next_attempt_at__lte=timezone.now()).order_by('priority', 'next_attempt_at', '-pk').first()
        if source is None:
            return 0
        found = references(source.input)
        error = 'redirect_without_product_id'
        deadline = time.monotonic() + 8
        for raw in source.input.get('urls', [])[:2]:
            if not identifiers.needs_redirect(raw):
                continue
            url = identifiers.unwrap(raw)
            # ClassificationState.key is varchar(64); keep the namespace plus 184 hash bits.
            cache_key = 'products:redirect:' + hashlib.sha256(url.encode()).hexdigest()[:46]
            cached = ClassificationState.objects.filter(pk=cache_key).values_list('value', flat=True).first() or {}
            if cached.get('expires_at', 0) > time.time():
                refs = cached.get('references', [])
            else:
                try:
                    page = (downloader or fetch)(url, limit=65536, deadline=deadline,
                        stop_at=lambda target: bool(identifiers.extract(target)))
                    refs = identifiers.extract(page.url)
                except ThumbnailError as exc:
                    error = str(exc)
                    refs = []
                if refs:
                    ClassificationState.objects.update_or_create(key=cache_key, defaults={'value': {
                        'references': refs, 'expires_at': time.time() + 86400}})
            found.extend({**row, 'evidence': 'redirect'} for row in refs)
            if time.monotonic() >= deadline:
                break
        attempts = source.attempts + 1
        if persist(source, found, status='ready' if found else 'retry' if attempts < 3 else 'unresolved',
                   error='' if found else error, attempts=attempts) and found:
            try_link(source.pk)
        return 1
    finally:
        close_old_connections()


def normalized_names(value):
    value = identity.normalize(value)
    for brand, replacement in sorted(identity.BRANDS.items(), key=lambda pair: -len(pair[0])):
        if brand == '매일두유':
            continue
        value = value.replace(brand, replacement)
    return identity.compact(value)


def supports(title, candidate, data=None):
    """A shared listing cannot override a conflicting flavor, size, model or accessory."""
    if identity.offer_issue(title) or identity.offer_issue(candidate.input_title):
        return False
    extracted = candidate.extraction
    if not extracted.get('name') or not extracted.get('attributes'):
        return False
    text = normalized_names(title)
    fields = [extracted.get(key) for key in ('brand', 'name', 'model', 'variant')]
    if any(normalized_names(field) not in text for field in fields if field):
        return False
    actual = identity.canonical_data({'model': extracted.get('model'), 'attributes': identity.facts(title)})['attributes']
    expected = dict(extracted['attributes'])
    left_container, right_container = actual.pop('container', ''), expected.pop('container', '')
    if left_container and right_container and left_container != right_container:
        return False
    if actual != expected:
        return False
    if data:
        for key in ('brand', 'model', 'variant'):
            left, right = data.get(key), extracted.get(key)
            if left and right and normalized_names(left) != normalized_names(right):
                return False
    return True


def match(job, data=None):
    source = ProductSource.objects.filter(pk=job.pk, status='ready', input__title=job.input_title).first()
    if source is None:
        return None
    own = list(source.references.values('key', 'namespace', 'scope', 'value', 'rank', 'canonical_url'))
    keys = {ref['key']: ref for ref in identifiers.preferred(own)}
    if not keys:
        return None
    references_query = ProductReference.objects.annotate(observed_title=KeyTextTransform('title', 'source__input')).filter(key__in=keys, source__status='ready',
        source__deal__product_assignment__status='ready', source__deal__product_assignment__product__is_active=True,
        observed_title=F('source__deal__product_assignment__input_title')).exclude(source_id=job.pk)
    refs = list(references_query.select_related('source__deal__product_assignment__product')
                .prefetch_related('source__references').order_by('-rank', 'id')[:81])
    if len(refs) > 80:
        return None
    candidates = {}
    for ref in refs:
        other = ref.source.deal.product_assignment
        # Broad parent IDs never bypass explicit option IDs on the reference side.
        other_refs = [{key: getattr(row, key) for key in ('key', 'namespace', 'scope', 'value', 'rank')}
                      for row in ref.source.references.all()]
        if ref.key not in {r['key'] for r in identifiers.preferred(other_refs)} or not supports(job.input_title, other, data):
            continue
        candidates.setdefault(other.product_id, (other, ref))
    if len(candidates) != 1:
        return None
    other, ref = next(iter(candidates.values()))
    result = dict(data or other.extraction)
    result['attributes'] = identity.canonical_data({'model': result.get('model'), 'attributes': identity.facts(job.input_title)})['attributes']
    result['shop_evidence'] = {'namespace': ref.namespace, 'scope': ref.scope, 'value': ref.value,
        'reference_deal_id': other.pk, 'canonical_url': ref.canonical_url, 'source_revision': source.revision}
    return other.product, result


def try_link(deal_id):
    from . import jobs
    with transaction.atomic():
        catalog.lock()
        job = DealProduct.objects.select_for_update().filter(pk=deal_id, manual_override=False).first()
        if job is None or job.status == 'ready':
            return 0
        matched = match(job)
        if not matched:
            return 0
        # An in-flight model response must not replace a newly confirmed ID link.
        job.request_revision += 1
        job.lease_until = None
        job.save(update_fields=['request_revision', 'lease_until'])
        return jobs.resolve(job, matched[1], 'identifier', target=matched[0])


def revisit_waiting(limit=30):
    """Newly learned references also wake older waits without filling the LLM queue."""
    state, _ = ClassificationState.objects.get_or_create(key='products:sources:revisit', defaults={'value': {}})
    cursor = state.value.get('cursor', 0)
    query = DealProduct.objects.filter(manual_override=False, product=None,
        deal__product_source__status='ready', deal__product_source__references__isnull=False)
    ids = list(query.filter(pk__gt=cursor).order_by('pk').values_list('pk', flat=True).distinct()[:min(limit, 30)])
    linked = sum(try_link(pk) for pk in ids)
    state.value = {'cursor': ids[-1] if ids else 0, 'at': time.time(),
                   'linked': state.value.get('linked', 0) + linked}
    state.save(update_fields=['value'])
    return linked
