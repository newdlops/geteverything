import copy
import importlib.util
from pathlib import Path
import unittest
import torch

spec=importlib.util.spec_from_file_location('product_train',Path(__file__).with_name('train.py'))
training=importlib.util.module_from_spec(spec);spec.loader.exec_module(training)


class KernelsTest(unittest.TestCase):
    def test_depthwise_cpu_path_matches_reference_values_and_input_gradients(self):
        torch.set_num_threads(1)
        for dtype in (torch.float32,torch.bfloat16):
            original=torch.nn.Conv1d(8,8,4,padding=3,groups=8,bias=True).to(dtype)
            fast=copy.deepcopy(original);training.install_cpu_kernels(fast)
            a=torch.randn(1,8,32,dtype=dtype,requires_grad=True);b=a.detach().clone().requires_grad_()
            expected=original(a);actual=fast(b)
            tolerance=0.02 if dtype==torch.bfloat16 else 1e-6
            torch.testing.assert_close(actual,expected,atol=tolerance,rtol=tolerance)
            expected.float().sum().backward();actual.float().sum().backward()
            torch.testing.assert_close(a.grad,b.grad,atol=tolerance,rtol=tolerance)


if __name__=='__main__':unittest.main()
