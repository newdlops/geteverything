#!/usr/bin/env python3
"""Report root precision and abstentions without confusing coverage with accuracy."""
import argparse
import json
from pathlib import Path
import time

from gadmin.categories.rules import classify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='gadmin/categories/tests/fixtures/titles.json')
    args = parser.parse_args()
    data = json.loads(Path(args.dataset).read_text())
    started = time.monotonic()
    assigned = correct = 0
    errors = []
    for row in data['titles']:
        result = classify(row['title'])
        if result.category:
            assigned += 1
            if result.category.split('.')[0] == row['expected_root']:
                correct += 1
            else:
                errors.append({'id': row['id'], 'title': row['title'], 'expected': row['expected_root'], 'actual': result.category})
    print(json.dumps({'provenance': data['provenance'], 'total': len(data['titles']), 'assigned': assigned,
        'correct': correct, 'precision': correct/assigned if assigned else None, 'coverage': assigned/len(data['titles']),
        'seconds': round(time.monotonic()-started, 3), 'errors': errors}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
