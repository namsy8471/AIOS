#!/usr/bin/env bash
set -euo pipefail
kernel=${1:?Pass the uncompressed ARM64 kernel}
out=${2:?Pass an output directory}
mkdir -p "$out"
root=$(mktemp -d)
trap 'rm -rf -- "$root"' EXIT
mkdir "$root/dev"
install -m 0755 target/aarch64-unknown-linux-musl/release/aios "$root/init"
strip "$root/init"
touch "$root/aios-boot-probe"
mknod -m 600 "$root/dev/kmsg" c 1 11
mknod -m 600 "$root/dev/console" c 5 1
if [[ ${3:-} == document ]]; then
  mkdir "$root/etc" "$root/work"
  touch "$root/etc/aios-document-console" "$root/etc/aios-stream-worker"
  printf '장보기' > "$root/work/note.txt"
  printf 'private' > "$root/work/sibling.txt"
  mknod -m 666 "$root/dev/null" c 1 3
fi
(cd "$root" && find . -print0 | cpio --null -o --format=newc --owner=0:0) | gzip > "$out/early-init.cpio.gz"
vm=(qemu-system-aarch64 -machine virt,gic-version=3 -cpu max -m 1024M -nic none \
  -display none -monitor none -serial stdio -no-reboot -kernel "$kernel" -initrd "$out/early-init.cpio.gz" \
  -append 'earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1')
if [[ ${3:-} == document ]]; then
  timeout 60s python3 tests/flip4_document.py "$out/console.log" "${vm[@]}"
  exit
fi
timeout 60s "${vm[@]}" | tee "$out/console.log"
python3 - "$out/console.log" <<'PY'
import json
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(errors="replace").splitlines()
record, = [json.loads(line.split("AIOS_EARLY_INIT ", 1)[1]) for line in lines if "AIOS_EARLY_INIT {" in line]
assert record["pid"] == 1 and record["arch"] == "aarch64", record
print(record)
PY
