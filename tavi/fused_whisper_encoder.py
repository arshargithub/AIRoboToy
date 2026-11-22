"""Encoder-only MLX attention optimization; decoder/alignment stays upstream.

No dependency files or model parameters are changed. Floating-point execution
order differs; saved-word and name-negative qualification is required.
"""
from types import MethodType


def fused_attention(self, q, k, v, mask=None):
    import mlx.core as mx
    if mask is not None:
        raise ValueError('Fused Whisper encoder expects unmasked self-attention')
    batch, length, state = q.shape
    dim = state // self.n_head
    q = q.reshape(batch, length, self.n_head, dim).transpose(0,2,1,3)
    k = k.reshape(k.shape[0], k.shape[1], self.n_head, dim).transpose(0,2,1,3)
    v = v.reshape(v.shape[0], v.shape[1], self.n_head, dim).transpose(0,2,1,3)
    result = mx.fast.scaled_dot_product_attention(q,k,v,scale=dim**-.5)
    return result.transpose(0,2,1,3).reshape(batch,length,state), None


def install(model):
    for block in model.encoder.blocks:
        block.attn.qkv_attention = MethodType(fused_attention,block.attn)
    return len(model.encoder.blocks)
