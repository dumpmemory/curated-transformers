from typing import Any, Mapping
import re
from torch import Tensor
from torch.nn import Parameter

from .config import RobertaConfig
from ..hf_util import _merge_qkv


def convert_hf_config(hf_config: Any) -> RobertaConfig:
    padding_id = hf_config["pad_token_id"]
    return RobertaConfig(
        attention_probs_dropout_prob=hf_config["attention_probs_dropout_prob"],
        embedding_width=hf_config["hidden_size"],
        hidden_act=hf_config["hidden_act"],
        hidden_dropout_prob=hf_config["hidden_dropout_prob"],
        hidden_width=hf_config["hidden_size"],
        intermediate_width=hf_config["intermediate_size"],
        layer_norm_eps=hf_config["layer_norm_eps"],
        # Positions embeddings for 0..padding_id are reserved.
        model_max_length=hf_config["max_position_embeddings"] - (padding_id + 1),
        max_position_embeddings=hf_config["max_position_embeddings"],
        num_attention_heads=hf_config["num_attention_heads"],
        num_hidden_layers=hf_config["num_hidden_layers"],
        padding_id=padding_id,
        type_vocab_size=hf_config["type_vocab_size"],
        vocab_size=hf_config["vocab_size"],
    )


def convert_hf_state_dict(params: Mapping[str, Parameter]) -> Mapping[str, Tensor]:
    out = {}

    # Strip the `roberta` prefix from XLM-Roberta model parameters.
    stripped_params = {re.sub(r"^roberta\.", "", k): v for k, v in params.items()}

    for name, parameter in stripped_params.items():
        if "encoder.layer." not in name:
            continue

        # TODO: Make these substitutions less ugly.

        # Remove the prefix and rename the internal 'layers' variable.
        name = re.sub(r"^encoder\.", "", name)
        name = re.sub(r"^layer", "layers", name)

        # The HF model has one more level of indirection for the output layers in their
        # attention heads and the feed-forward network layers.
        name = re.sub(r"\.attention\.self\.(query|key|value)", r".mha.\1", name)
        name = re.sub(r"\.attention\.(output)\.dense", r".mha.\1", name)
        name = re.sub(
            r"\.attention\.output\.LayerNorm", r".attn_output_layernorm", name
        )
        name = re.sub(r"\.(intermediate)\.dense", r".ffn.\1", name)
        name = re.sub(r"(\.\d+)\.output\.LayerNorm", r"\1.ffn_output_layernorm", name)
        name = re.sub(r"(\.\d+)\.(output)\.dense", r"\1.ffn.\2", name)

        out[name] = parameter

    # Rename and move embedding parameters to the inner BertEmbeddings module.
    out["embeddings.inner.word_embeddings.weight"] = stripped_params[
        "embeddings.word_embeddings.weight"
    ]
    out["embeddings.inner.token_type_embeddings.weight"] = stripped_params[
        "embeddings.token_type_embeddings.weight"
    ]
    out["embeddings.inner.position_embeddings.weight"] = stripped_params[
        "embeddings.position_embeddings.weight"
    ]
    out["embeddings.inner.layer_norm.weight"] = stripped_params[
        "embeddings.LayerNorm.weight"
    ]
    out["embeddings.inner.layer_norm.bias"] = stripped_params[
        "embeddings.LayerNorm.bias"
    ]

    return _merge_qkv(out)