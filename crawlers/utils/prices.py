"""Compatibility entry point for the shared, evidence-based price parser."""
from gadmin.metrics.money import legacy_subject_price


def extract_subject_price(subject: str) -> str | int:
    return legacy_subject_price(subject)
