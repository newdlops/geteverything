#!/usr/bin/env python3
"""Update the category worker without restarting crawlers or changing model policy."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

CONFIG = Path('/etc/geteverything-categories/runtime.json')
UNITS = ['geteverything-categories.service', 'geteverything-category-model-guard.service',
         'geteverything-category-model-guard.timer', 'geteverything-product-quality.service',
         'geteverything-product-quality.timer']


def run(args, timeout=30, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(args[0] + ' failed: ' + result.stderr[-1200:])
    return result.stdout.strip()


def main():
    source = Path(__file__).resolve().parents[2]
    config = json.loads(CONFIG.read_text())
    previous = dict(config)
    assert Path('/etc/geteverything-categories/worker.env').is_file()
    base_id = run(['docker', 'inspect', '--format', '{{.Image}}', 'crawlers-bot'])
    base_tag = 'geteverything-categories-base:' + base_id.split(':')[-1][:12]
    run(['docker', 'tag', base_id, base_tag])
    with tempfile.TemporaryDirectory(prefix='category-build-') as temporary:
        root = Path(temporary)
        for name in ('categories', 'metrics', 'products', 'deals', 'thumbnails'):
            shutil.copytree(source/'gadmin'/name, root/'gadmin'/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(source/'ops/deal-categories/Dockerfile', root/'Dockerfile')
        run(['docker', 'build', '--build-arg', 'BASE_IMAGE=' + base_tag, '-t', 'geteverything-category-worker:latest', str(root)], timeout=120)
    image = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', 'geteverything-category-worker:latest'])
    common = ['docker', 'run', '--rm', '--memory=192m', '--memory-swap=192m', '--cpus=0.15', '--read-only', '--tmpfs=/tmp:size=32m']
    run([*common, '--network=none', image, 'python', '-m', 'unittest', 'gadmin.categories.tests.test_rules', 'gadmin.categories.tests.test_context', 'gadmin.metrics.tests.test_parser', 'gadmin.metrics.tests.test_fx'], timeout=60)
    run([*common, '--network=none', image, 'python', '-m', 'django', 'test',
         'gadmin.products.tests.test_products.IdentityTests',
         'gadmin.products.tests.test_quality.ProductQualityTests',
         'gadmin.products.tests.test_products.ProductWorkflowTests.test_conflicting_containers_sizes_and_flavors_are_not_inferred',
         'gadmin.products.tests.test_products.ProductWorkflowTests.test_legacy_unknown_product_with_conflicting_container_history_is_not_reused',
         'gadmin.products.tests.test_sft.TrainingDataTests.test_grounded_suffix_cannot_stand_in_for_the_complete_product_subline',
         'gadmin.products.tests.test_sft.TrainingDataTests.test_suffix_repair_abstains_from_noisy_or_measurement_bearing_title_lines',
         'gadmin.products.tests.test_sft.ReviewedFeedbackTests.test_operator_corrected_extraction_is_exported_for_lora_training',
         'gadmin.products.tests.test_sft.ReviewedFeedbackTests.test_assignment_without_extraction_confirmation_does_not_label_llm_fields',
         'gadmin.products.tests.test_deduplicate.StableIdentityTests',
         'gadmin.products.tests.test_deduplicate.DeduplicateTests.test_conflicting_container_evidence_splits_old_inference_and_keeps_explicit_uuid',
         'gadmin.products.tests.test_deduplicate.DeduplicateTests.test_scoped_repair_splits_conflicting_container_history_without_touching_other_products',
         'gadmin.products.tests.test_deduplicate.DeduplicateTests.test_scoped_repair_unifies_same_title_alias_with_differently_partitioned_fields',
         '--settings=gadmin.products.tests.worker_settings', '--verbosity=0'], timeout=90)
    run([*common, '--env-file=/etc/geteverything-categories/worker.env', image, 'python', '-m', 'gadmin.categories.worker', '--status'], timeout=60)
    backup = Path('/root/category-worker-backups')/str(time.time_ns())
    backup.mkdir(parents=True, mode=0o700)
    (backup/'runtime.json').write_text(json.dumps(previous, indent=2))
    destination = Path('/usr/local/lib/geteverything-categories')
    destination.mkdir(exist_ok=True)
    for name in ('run.py', 'guard.py', 'quality.py'):
        shutil.copyfile(source/'ops/deal-categories'/name, destination/name)
        (destination/name).chmod(0o755)
    for name in UNITS:
        target = Path('/etc/systemd/system')/name
        if target.exists(): shutil.copyfile(target, backup/name)
        shutil.copyfile(source/'ops/deal-categories'/name, target)
        target.chmod(0o644)
    run(['systemd-analyze', 'verify', *[str(Path('/etc/systemd/system')/name) for name in UNITS]])
    config['worker_image'] = image
    CONFIG.write_text(json.dumps(config, indent=2))
    CONFIG.chmod(0o600)
    try:
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', 'geteverything-categories.service', 'geteverything-category-model-guard.timer'])
        run(['systemctl', 'enable', 'geteverything-product-quality.timer'])
        run(['systemctl', 'restart', 'geteverything-categories.service'], timeout=280)
        run(['systemctl', 'start', 'geteverything-category-model-guard.timer'])
        run(['systemctl', 'start', 'geteverything-product-quality.timer'])
        time.sleep(4)
        assert run(['systemctl', 'is-active', 'geteverything-categories.service']) == 'active'
        assert run(['docker', 'inspect', '--format', '{{.State.Running}}', 'geteverything-category-worker']) == 'true'
    except Exception:
        CONFIG.write_text(json.dumps(previous, indent=2))
        if previous.get('worker_image'):
            run(['systemctl', 'restart', 'geteverything-categories.service'], timeout=280, check=False)
        else:
            run(['systemctl', 'stop', 'geteverything-categories.service'], timeout=280, check=False)
        raise
    report = {'at': time.time(), 'worker_image': image, 'base_image': base_id, 'backup': str(backup)}
    (backup/'deployment.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
