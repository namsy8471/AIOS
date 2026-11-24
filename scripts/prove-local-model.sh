#!/usr/bin/env bash
set -euo pipefail
stage=$(mktemp -d)
model=qwen2.5-3b-instruct-q4_k_m.gguf
server_pid=
cleanup() {
  if [[ -n "$server_pid" ]]; then kill "$server_pid" 2>/dev/null || true; wait "$server_pid" || true; fi
  rm -rf -- "$stage"
}
trap cleanup EXIT
curl -fsSL --retry 3 -o "$stage/llama.tar.gz" https://github.com/ggml-org/llama.cpp/releases/download/b12675/llama-b12675-bin-ubuntu-x64.tar.gz
curl -fsSL --retry 3 -o "$stage/$model" "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/7dabda4d13d513e3e842b20f0d435c732f172cbe/$model"
(cd "$stage" && sha256sum -c <<CHECKSUMS
c4f5ff106835e3ec8a68509bac07286318c884238cec72de4ee0753e80d35157  llama.tar.gz
626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d  $model
CHECKSUMS
)
tar -xf "$stage/llama.tar.gz" -C "$stage"
server=$(find "$stage" -type f -name llama-server -print -quit)
"$server" -m "$stage/$model" --alias Qwen2.5-3B-Instruct-Q4_K_M -c 4096 -t 3 --port 18080 --host 127.0.0.1 >"$stage/model.log" 2>&1 &
server_pid=$!
for _ in {1..90}; do
  if curl -fsS http://127.0.0.1:18080/health >/dev/null 2>&1; then break; fi
  if ! kill -0 "$server_pid" 2>/dev/null; then cat "$stage/model.log"; exit 1; fi
  sleep 1
done
if ! python3 build/runtime/aios_mvp.py --model-port 18080 --output "$stage/proof"; then
  tail -40 "$stage/model.log" >&2
  tail -40 "$stage/proof/first-boot.log" >&2
  exit 1
fi
cp "$stage/proof/proof.json" build/runtime/model-proof.json
cat build/runtime/model-proof.json
