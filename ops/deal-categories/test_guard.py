import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('category_guard', Path(__file__).with_name('guard.py'))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def test_training_reserves_inference_budget(self):
        self.assertEqual(guard.decision(30, 8*1024**3, 40, True, 4, training=True), (False, 0))

    def test_busy_crawler_unloads_even_running_model(self):
        self.assertEqual(guard.decision(80, 8*1024**3, 100, True, 10), (False, 0))

    def test_model_reserves_headroom_and_does_not_flap_near_the_start_threshold(self):
        self.assertEqual(guard.decision(59, 8*1024**3, 40, False, 0), (False, 1))
        self.assertEqual(guard.decision(59, 8*1024**3, 40, False, 1), (True, 2))
        self.assertEqual(guard.decision(70, 6*1024**3, 40, True, 2), (True, 0))
        self.assertEqual(guard.decision(60, 6*1024**3, 40, False, 1), (False, 0))

    def test_memory_pressure_unloads_model(self):
        self.assertEqual(guard.decision(10, 2*1024**3, 100, True, 10), (False, 0))

    def test_two_calm_samples_required_to_start(self):
        self.assertEqual(guard.decision(30, 8*1024**3, 100, False, 0), (False, 1))
        self.assertEqual(guard.decision(30, 8*1024**3, 100, False, 1), (True, 2))

    def test_no_work_releases_memory(self):
        self.assertEqual(guard.decision(30, 8*1024**3, 0, True, 4), (False, 0))
