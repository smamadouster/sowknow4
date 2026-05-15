"""
Export intfloat/multilingual-e5-large to ONNX + dynamic INT8 quantization.

Bypasses optimum CLI bugs by using torch.onnx.export directly
and onnxruntime.quantize_dynamic for INT8.

Outputs land in /models/e5-large-onnx-int8/.
"""

import os
from pathlib import Path

import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModel, AutoTokenizer

MODEL_ID = "intfloat/multilingual-e5-large"
OUT_DIR = Path("/models/e5-large-onnx-int8")
FP32_DIR = OUT_DIR / "_fp32"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FP32_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {MODEL_ID}...")
    model = AutoModel.from_pretrained(MODEL_ID, cache_dir="/models")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir="/models")
    model.eval()

    print("Saving tokenizer...")
    tokenizer.save_pretrained(OUT_DIR)

    print("Exporting to ONNX (FP32, opset 18)...")
    dummy = tokenizer("passage: test", return_tensors="pt", max_length=512, truncation=True)
    torch.onnx.export(
        model,
        (dummy["input_ids"], dummy["attention_mask"]),
        str(FP32_DIR / "model.onnx"),
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "last_hidden_state": {0: "batch_size", 1: "sequence_length"},
        },
        opset_version=18,
        do_constant_folding=True,
    )

    print("Applying dynamic INT8 quantization...")
    quantize_dynamic(
        model_input=str(FP32_DIR / "model.onnx"),
        model_output=str(OUT_DIR / "model_quantized.onnx"),
        weight_type=QuantType.QInt8,
    )

    fp32_size = (FP32_DIR / "model.onnx").stat().st_size / 1024 / 1024
    int8_size = (OUT_DIR / "model_quantized.onnx").stat().st_size / 1024 / 1024
    print(f"\nDone.")
    print(f"  FP32: {fp32_size:.1f} MB")
    print(f"  INT8: {int8_size:.1f} MB")
    print(f"  Compression: {fp32_size / int8_size:.1f}x")


if __name__ == "__main__":
    main()
