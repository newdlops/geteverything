import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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


class ImportTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.data={'train':[{'title':'reviewed training title'}],
                   'validation':[{'title':'held-out title'}],'version':'test-prompt'}
        digest=hashlib.sha256(json.dumps(self.data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        self.data['sha256']=digest
        self.base={'revision':'pinned-base'}
        recipe={'epochs':4,'max_steps':1200}
        run_id=hashlib.sha256((digest+self.base['revision']+self.data['version']+
                              json.dumps(recipe,sort_keys=True)).encode()).hexdigest()[:20]
        best=self.root/'runs'/run_id/'best';best.mkdir(parents=True)
        (best/'adapter_model.safetensors').write_bytes(b'checkpoint bytes')
        (best/'adapter_config.json').write_text('{}')
        self.state={'status':'trained_awaiting_generation_eval','probe':False,'promoted':False,
                    'base_revision':self.base['revision'],'dataset_sha256':digest,
                    'prompt_version':self.data['version'],'recipe':recipe,'run_id':run_id,
                    'training_examples':1,'validation_examples':1,'step':4,'best_step':3,
                    'baseline_validation_loss':0.2,'final_validation_loss':0.1,'lora_b_squared_norm':0.02,
                    'adapter':'/training/runs/'+run_id+'/best',
                    'adapter_sha256':hashlib.sha256(b'checkpoint bytes').hexdigest()}

    def test_completed_import_requires_matching_model_data_run_and_weights(self):
        runner.validate_import(self.state,self.data,self.base,self.root)
        for change in ({'probe':True},{'base_revision':'other-base'},
                       {'run_id':'../other'},{'adapter_sha256':'0'*64},
                       {'step':0},{'final_validation_loss':float('nan')},
                       {'adapter':'/tmp/unrelated/best'}):
            with self.subTest(change=change),self.assertRaises(AssertionError):
                runner.validate_import(self.state|change,self.data,self.base,self.root)

    def test_modified_dataset_is_rejected_even_with_original_checksum_field(self):
        changed=copy.deepcopy(self.data)
        changed['validation'][0]['title']='changed title'
        with self.assertRaises(AssertionError):
            runner.validate_import(self.state,changed,self.base,self.root)


class PromotionReadinessTests(unittest.TestCase):
    def response(self, body=b'{}'):
        reply=MagicMock()
        reply.__enter__.return_value.status=200
        reply.__enter__.return_value.read.return_value=body
        return reply

    def test_startup_retry_and_control_calls_allow_a_cold_inference(self):
        with patch.object(runner.urllib.request,'urlopen',side_effect=[
                OSError('loading'),self.response(),self.response(),
                self.response(b'[{"id":0,"scale":0.0}]')]) as request,patch.object(runner.time,'sleep') as sleep:
            runner.disable_default_adapter()
        self.assertEqual(request.call_count,4)
        self.assertEqual(request.call_args_list[0].args[0],'http://127.0.0.1:8094/health')
        self.assertEqual(request.call_args_list[2].args[0].data,b'[]')
        self.assertEqual([call.kwargs['timeout'] for call in request.call_args_list],[10,10,240,240])
        sleep.assert_called_once_with(20)

    def test_unready_model_stops_after_three_attempts(self):
        with patch.object(runner.urllib.request,'urlopen',side_effect=OSError('unready')) as request,\
                patch.object(runner.time,'sleep'),self.assertRaises(OSError):
            runner.disable_default_adapter()
        self.assertEqual(request.call_count,3)

    def test_unconfirmed_default_disable_cannot_promote(self):
        with patch.object(runner.urllib.request,'urlopen',side_effect=[self.response(),self.response(),
                self.response(b'[{"id":0,"scale":1.0}]')]),self.assertRaises(AssertionError):
            runner.disable_default_adapter()


if __name__=='__main__':unittest.main()
