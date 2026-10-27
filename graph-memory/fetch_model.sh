#!/bin/bash
# Download the BGE-small ONNX model into the data dir with plain curl.
# Exists because huggingface_hub's HEAD-based downloader chokes on CloudFront
# responses that omit Content-Length ("Distant resource does not have a
# Content-Length"); direct GETs work fine.
# Pinned to one Hugging Face commit, and every file is checked against its sha256
# (taken 2026-10-27 from the copy fetched on 2026-08-30, which matches this commit's blobs).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
MODEL_DIR="$("$PYTHON" "$HERE/../rekall_config.py" DATA)/model"
REV=aa8f8b060edb00e03bfdd08813a2949946c8ba55
mkdir -p "$MODEL_DIR"
SUMS="13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd  config.json
51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431  model_optimized.onnx
99881c45e073696289224931dd48694398bc6bcd1fe7cb7018bca1e0cc00e1fc  ort_config.json
5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a  special_tokens_map.json
d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66  tokenizer.json
0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53  tokenizer_config.json
07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3  vocab.txt"
echo "$SUMS" | while read -r _ f; do
  curl -sSL --fail -o "$MODEL_DIR/$f" "https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q/resolve/$REV/$f"
  echo "fetched $f"
done
SHA="shasum -a 256"
command -v shasum >/dev/null || SHA=sha256sum   # Git Bash on Windows ships sha256sum only
(cd "$MODEL_DIR" && echo "$SUMS" | $SHA -c -) || { echo "model checksum mismatch in $MODEL_DIR; not using it" >&2; exit 1; }
