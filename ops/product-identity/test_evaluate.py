import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gadmin.products.sft import bootstrap_rows, dataset, VERSION

spec=importlib.util.spec_from_file_location('product_evaluate',Path(__file__).with_name('evaluate.py'))
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)


class EvaluationProgressTests(unittest.TestCase):
    def run_evaluation(self, invalid_candidate=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            work=root/'runs'/'example';work.mkdir(parents=True)
            (work/'adapter.gguf').write_bytes(b'test-adapter')
            data=dataset(bootstrap_rows())
            (root/'dataset.json').write_text(json.dumps(data))
            status={'status':'trained_awaiting_generation_eval','run_id':'example','probe':False,
                    'dataset_sha256':data['sha256'],'loss_gate':True,'lora_b_squared_norm':.1,
                    'promoted':False,'prompt_version':VERSION}
            (root/'status.json').write_text(json.dumps(status))
            expected={row['title']:row['target'] for row in data['validation']}
            observed=[]
            class Model:
                def structured(self, system, value, schema, max_tokens, adapter):
                    observed.append(json.loads((root/'status.json').read_text()))
                    return expected[value['title']] if adapter==0 and not invalid_candidate else {}
            with patch.object(evaluation,'LocalModel',return_value=Model()),patch('sys.argv',[
                    'evaluate.py','--root',str(root),'--dataset',str(root/'dataset.json')]),contextlib.redirect_stdout(io.StringIO()):
                evaluation.main()
            return observed,json.loads((root/'status.json').read_text()),json.loads((root/'evaluation.json').read_text())

    def test_live_status_covers_each_request_and_final_validation(self):
        observed,status,result=self.run_evaluation()
        count=len(dataset(bootstrap_rows())['validation'])
        self.assertEqual([row['evaluation_completed'] for row in observed],list(range(2*count)))
        self.assertTrue(all(row['status']=='evaluating' and row['evaluation_total']==2*count for row in observed))
        self.assertEqual([row['evaluation_mode'] for row in observed],['baseline']*count+['candidate']*count)
        self.assertEqual(status,result)
        self.assertEqual(status['status'],'validated')
        self.assertEqual(status['evaluation_completed'],2*count)
        self.assertGreater(result['candidate']['pairs']['same_pairs'],10)
        self.assertGreater(result['candidate']['pairs']['different_pairs'],20)
        self.assertFalse(status['promoted'])

    def test_rejected_candidate_does_not_leave_a_training_status(self):
        _,status,result=self.run_evaluation(invalid_candidate=True)
        self.assertEqual(status,result)
        self.assertEqual(status['status'],'rejected')
        self.assertFalse(status['gate']['passed'])
        self.assertFalse(status['promoted'])

    def test_resume_requires_same_context_and_an_exact_prefix_of_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);context={'adapter_sha256':'one','dataset_sha256':'data'}
            row={'title':'held-out example','target':{'is_product':False}}
            self.assertEqual(evaluation.resume_details(root,context,[row]),[])
            done={'mode':'baseline','title':row['title'],'expected':row['target'],
                  'actual':{},'seconds':2,'correct':False,'valid':False,'false_merge':False}
            (root/'generation-progress.json').write_text(json.dumps([done]))
            self.assertEqual(evaluation.resume_details(root,context,[row]),[done])
            with self.assertRaises(RuntimeError):
                evaluation.resume_details(root,context|{'adapter_sha256':'different'},[row])
            with self.assertRaises(AssertionError):
                evaluation.resume_details(root,context,[row|{'title':'changed title'}])


if __name__=='__main__':unittest.main()
