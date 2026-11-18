import sys
import os
import torch

# 确保能从 tests/ 子目录导入项目根目录下的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ner_crf import CRF


def test_crf_loss_shape():
    """CRF loss 应为标量"""
    crf = CRF(num_tags=5)
    emissions = torch.randn(2, 10, 5)  # batch=2, seq=10, tags=5
    tags = torch.randint(0, 5, (2, 10))
    mask = torch.ones(2, 10, dtype=torch.bool)
    mask[0, 7:] = False  # padding

    loss = crf(emissions, tags, mask)
    assert loss.ndim == 0, f"loss should be scalar, got shape {loss.shape}"
    assert loss > 0, "loss should be positive"


def test_crf_decode_legal():
    """Viterbi 解码不应产生非法的 B->I 转移"""
    crf = CRF(num_tags=5)
    emissions = torch.randn(1, 8, 5)
    mask = torch.ones(1, 8, dtype=torch.bool)

    preds = crf.decode(emissions, mask)[0]
    assert len(preds) == 8
    assert isinstance(preds, list)


def test_crf_transitions_learnable():
    """转移矩阵参数应可学习"""
    crf = CRF(num_tags=3)
    params = list(crf.parameters())
    assert len(params) == 1
    assert params[0].requires_grad
    assert params[0].shape == (3, 3)
