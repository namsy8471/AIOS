#!/usr/bin/env bash
# Prepare a separate Flip4 ext4 disk with an ARM64 CPU-only inference runtime.
set -euo pipefail
bundle=${1:?Pass the Flip4 bundle directory}
disk=${2:?Pass a new output disk path}
[[ $(uname -m) == aarch64 && ! -e "$disk" ]]
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
rev=c212d25ad34ff1fdf775793cda07e009560cf66b
curl -fsSL --retry 3 "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/$rev" | tar -xz -C "$stage"
cmake -S "$stage/llama.cpp-$rev" -B "$stage/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF -DGGML_BLAS=OFF -DLLAMA_BUILD_EXAMPLES=ON \
  -DCMAKE_EXE_LINKER_FLAGS=-static
cmake --build "$stage/build" --target llama-simple -j 4
binary="$stage/build/bin/llama-simple"
strip "$binary"
if readelf -l "$binary" | grep 'INTERP'; then exit 1; fi
model=qwen2.5-0.5b-instruct-q4_k_m.gguf
curl -fsSL --retry 3 "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/$model" -o "$stage/model.gguf"
(cd "$stage" && echo '74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db  model.gguf' | sha256sum -c -)
cp "$bundle/starter.raw" "$stage/disk.raw"
truncate -s 768M "$stage/disk.raw"
resize2fs "$stage/disk.raw"
debugfs -w "$stage/disk.raw" <<CMDS
mkdir /opt
mkdir /opt/model
write $binary /opt/model/llama-simple
write $stage/model.gguf /opt/model/model.gguf
CMDS
e2fsck -fn "$stage/disk.raw"
mv "$stage/disk.raw" "$disk"
