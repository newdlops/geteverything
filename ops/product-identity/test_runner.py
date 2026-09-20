import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('training_runner',Path(__file__).with_name('runner.py'))
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class ResourceTests(unittest.TestCase):
    def test_memory_pressure_stops_training_before_crawler_headroom_is_consumed(self):
        self.assertEqual(runner.pressure_action(40,1024**3,0),'stop')

    def test_sustained_cpu_saturation_pauses_and_recovers(self):
        self.assertEqual(runner.pressure_action(81,4*1024**3,1),'keep')
        self.assertEqual(runner.pressure_action(81,4*1024**3,2),'pause')
        self.assertEqual(runner.pressure_action(70,4*1024**3,0),'keep')
        self.assertEqual(runner.pressure_action(63,4*1024**3,0),'resume')

    def test_training_policy_rejects_unbounded_resource_requests(self):
        self.assertEqual(runner.training_policy({})['epochs'],4)
        for changes in ({'cpu':2},{'training_hours':48},{'max_steps':100000},{'rank':128}):
            with self.assertRaises(AssertionError):runner.training_policy({'training':changes})


if __name__=='__main__':unittest.main()
