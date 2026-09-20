import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('product_train',Path(__file__).with_name('train.py'))
training=importlib.util.module_from_spec(spec);spec.loader.exec_module(training)


class RecipeTests(unittest.TestCase):
    def test_warmup_then_decay_remains_positive_and_within_budget(self):
        rates=[training.learning_rate(i,984,8e-5) for i in range(984)]
        self.assertGreater(rates[19],rates[0])
        self.assertLess(rates[-1],rates[20])
        self.assertTrue(all(0<rate<=8e-5 for rate in rates))

    def test_frozen_cache_is_independent_of_lora_recipe_but_not_model_or_tokens(self):
        first=training.cache_key('base-revision',23,[1,2,3])
        self.assertEqual(first,training.cache_key('base-revision',23,[1,2,3]))
        for revision,layer,ids in [('other',23,[1,2,3]),('base-revision',19,[1,2,3]),('base-revision',23,[1,2,4])]:
            self.assertNotEqual(first,training.cache_key(revision,layer,ids))


if __name__=='__main__':unittest.main()
