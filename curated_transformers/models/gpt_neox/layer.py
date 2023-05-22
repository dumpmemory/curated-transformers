from typing import Optional, Tuple
from torch import Tensor
import torch
from torch.nn import Module

from ..feedforward import PointwiseFeedForward
from ..attention import (
    AttentionMask,
    KeyValueCache,
    SelfAttentionWithRotaryEmbeddings,
)
from .config import GPTNeoXAttentionConfig, GPTNeoXLayerConfig


class GPTNeoXDecoderLayer(Module):
    """GPT-NeoX (Black et al, 2022) layer."""

    def __init__(
        self, layer_config: GPTNeoXLayerConfig, attention_config: GPTNeoXAttentionConfig
    ):
        """
        :param layer_config: Layer configuration.
        :param attention_config: Attention configuration.
        """
        super().__init__()

        self.mha = SelfAttentionWithRotaryEmbeddings(
            dropout_prob=attention_config.dropout_prob,
            hidden_width=attention_config.hidden_width,
            num_attention_heads=attention_config.num_attention_heads,
            rotary_fraction=attention_config.rotary_fraction,
            rotary_base=attention_config.rotary_base,
            split_heads_before_chunk=True,
        )
        self.attn_output_dropout = torch.nn.Dropout(p=layer_config.dropout_prob)
        self.mha_layer_norm = torch.nn.LayerNorm(
            layer_config.hidden_width, eps=layer_config.layer_norm_eps
        )

        self.ffn = PointwiseFeedForward(
            hidden_act=layer_config.hidden_act,
            hidden_width=layer_config.hidden_width,
            intermediate_width=layer_config.intermediate_width,
        )
        self.ffn_layer_norm = torch.nn.LayerNorm(
            layer_config.hidden_width, eps=layer_config.layer_norm_eps
        )
        self.ffn_output_dropout = torch.nn.Dropout(p=layer_config.dropout_prob)

    def forward(
        self,
        x: Tensor,
        attention_mask: AttentionMask,
        cache: Optional[KeyValueCache] = None,
        positions: Optional[Tensor] = None,
        store_cache: bool = False,
    ) -> Tuple[Tensor, Optional[KeyValueCache]]:
        """
        Apply the GPT-NeoX layer to the given piece hidden representations.

        :param x: Hidden representations to apply the layer to.
        :param attention_mask: Attention mask. Sequence elements for which the
            corresponding mask element is set to ``False`` are ignored
            during attention calculation.
        :param cache: Key/value cache to avoid recomputing
            key/value representations for tokens that were previously seen.
        :param positions: Input positions. Positions are needed to
            look up rotary embeddings. Normally, these positions are calculated
            automatically. But if the positions deviate for some reason, they
            can be provided through this argument.
        :param store_cache: Whether to cache the key/value representations for
            future reuse.
        :returns: Layer output.

        Shapes:
            x - (batch, seq_len, width)
            attention_mask - (batch, seq_len)
        """
        attn_out, cache = self.mha(
            self.mha_layer_norm(x),
            attention_mask,
            cache=cache,
            store_cache=store_cache,
            positions=positions,
            use_causal_mask=True,
        )
        attn_out = self.attn_output_dropout(attn_out)
        ffn_out = self.ffn(self.ffn_layer_norm(x))
        ffn_out = self.ffn_output_dropout(ffn_out)

        # Parallel attention & feed-forward, Section 2.1.2
        return x + attn_out + ffn_out, cache