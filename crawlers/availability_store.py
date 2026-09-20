"""Persist observations without rewriting prices, images or price history."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

from gadmin.deals.models import Deal, DealAvailability


def record_observation(article_id, observation, now=None):
    now = now or timezone.now()
    outcome = observation['outcome']
    if outcome not in {'active', 'ended', 'deleted', 'missing', 'unknown'}:
        raise ValueError('Invalid availability observation')
    with transaction.atomic():
        deal = Deal.objects.select_for_update().filter(article_id=article_id).only('id', 'is_end').first()
        if deal is None:
            return None  # A missing page must never create a blank deal.
        status, created = DealAvailability.objects.get_or_create(deal=deal, defaults={
            'state': 'ended' if deal.is_end else 'unknown', 'checked_at': now})
        if not created and status.checked_at > now:
            return status
        status.checked_at = now
        status.last_outcome = outcome
        status.evidence = observation.get('evidence', '')[:200]
        if outcome == 'missing':
            if status.missing_since is None:
                status.missing_since, status.missing_count = now, 1
            elif now - status.missing_since >= timedelta(minutes=15):
                status.missing_count = min(2, status.missing_count + 1)
            if status.missing_count >= 2:
                status.state = 'deleted'
                status.ended_at = status.ended_at or now
            status.next_check_at = now + (timedelta(hours=72) if status.state == 'deleted' else timedelta(minutes=30))
        else:
            status.missing_since, status.missing_count = None, 0
            if outcome != 'unknown':
                status.state = outcome
                status.ended_at = (status.ended_at or now) if outcome in {'ended', 'deleted'} else None
            hours = 72 if status.state in {'ended', 'deleted'} else 12
            status.next_check_at = now + timedelta(hours=hours if outcome != 'unknown' else 2)
        if status.state != 'unknown':
            ended = status.state in {'ended', 'deleted'}
            if deal.is_end != ended:
                Deal.objects.filter(pk=deal.pk).update(is_end=ended)
        status.save()
        return status


def due_deals(community, limit=5, now=None):
    now = now or timezone.now()
    # Recently crawled rows are covered by normal requests. Null checks sort first
    # so older unchecked posts are not starved by repeatedly checking newer ones.
    return list(Deal.objects.filter(community_name=community, origin_url__isnull=False).exclude(origin_url='').filter(
        Q(update_at__lt=now-timedelta(hours=12)) | Q(availability__last_outcome='missing')
    ).filter(
        Q(availability__isnull=True) | Q(availability__next_check_at__lte=now)
    ).annotate(check_priority=Case(When(availability__last_outcome='missing', then=Value(0)),
        When(availability__isnull=True, then=Value(1)), default=Value(2)))
        .order_by('check_priority', F('availability__checked_at').asc(nulls_first=True), '-id')
        .values('article_id', 'origin_url')[:limit])
