#!/bin/bash
# Download the BGE-small ONNX model into the data dir with plain curl.
# Exists because huggingface_hub's HEAD-based downloader chokes on CloudFront
# responses that omit Content-Length ("Distant resource does not have a
# Content-Length"); direct GETs work fine.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
MODEL_DIR="$(python3 "$HERE/../rekall_config.py" DATA)/model"
mkdir -p "$MODEL_DIR"
for f in config.json model_optimized.onnx ort_config.json special_tokens_map.json tokenizer.json tokenizer_config.json vocab.txt; do
  curl -sSL --fail -o "$MODEL_DIR/$f" "https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q/resolve/main/$f"
  echo "fetched $f"
done
