"""
Export intfloat/multilingual-e5-large to ONNX + dynamic INT8 quantization.

Outputs land in /models/e5-large-onnx-int8/. Run inside any environment with
optimum[onnxruntime] installed — the quantized model is portable.

Usage:
    pip install "optimum[onnxruntime]==1.21.4" "onnxruntime==1.18.1"
    python scripts/export_e5_to_onnx.py
"""

from pathlib import Path

from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig
from transformers import AutoTokenizer

MODEL_ID = "intfloat/multilingual-e5-large"
OUT_DIR = Path("/models/e5-large-onnx-int8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fp32_dir = OUT_DIR / "_fp32"

    print(f"Exporting {MODEL_ID} to ONNX (FP32)...")
    model = ORTModelForFeatureExtraction.from_pretrained(MODEL_ID, export=True)
    model.save_pretrained(fp32_dir)
    AutoTokenizer.from_pretrained(MODEL_ID).save_pretrained(OUT_DIR)

    print("Applying dynamic INT8 quantization (avx512_vnni)...")
    quantizer = ORTQuantizer.from_pretrained(fp32_dir)
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
    quantizer.quantize(save_dir=OUT_DIR, quantization_config=qconfig)

    print(f"\nDone. Model in {OUT_DIR}:")
    for p in sorted(OUT_DIR.iterdir()):
        if p.is_file():
            print(f"  {p.name}: {p.stat().st_size / 1024 / 1024:.1f} MB")

    # Print CPU flags hint
    print("\nHint: check /proc/cpuinfo | grep avx512_vnni on your host.")
    print("      If VNNI is unavailable, swap the qconfig line for:")
    print("      AutoQuantizationConfig.avx2(is_static=False, per_channel=False)")


if __name__ == "__main__":
    main()
