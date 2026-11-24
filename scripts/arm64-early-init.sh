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
mknod -m 600 "$root/dev/kmsg" c 1 11
mknod -m 600 "$root/dev/console" c 5 1
if [[ ${3:-} == flip4-board-probe ]]; then
  mkdir -p "$root/etc" "$root/proc" "$root/sys" "$root/pstore"
  touch "$root/etc/aios-flip4-board-probe"
  (cd "$root" && find . -print0 | cpio --null -o --format=newc --owner=0:0) | gzip > "$out/board-probe-init.cpio.gz"
  exit
fi
touch "$root/aios-boot-probe"
if [[ ${3:-} == pstore ]]; then
  mkdir "$root/sys" "$root/pstore"
  touch "$root/aios-pstore-probe"
fi
if [[ ${3:-} == document || ${3:-} == disk || ${3:-} == split-disk ]]; then
  mkdir "$root/etc" "$root/work"
  touch "$root/etc/aios-document-console" "$root/etc/aios-stream-worker"
  printf '장보기' > "$root/work/note.txt"
  printf 'private' > "$root/work/sibling.txt"
  mknod -m 666 "$root/dev/null" c 1 3
fi
if [[ ${3:-} == split-disk ]]; then
  mkdir "$root/proc" "$root/work-data"
  mv "$root/work/"*.txt "$root/work-data/"
  touch "$root/etc/aios-qemu-work-partition"
  mknod -m 600 "$root/dev/sda2" b 8 2
  # Keep ext4 data and partition offsets aligned to 1 MiB.
  truncate -s 16M "$out/work.ext4"
  mkfs.ext4 -q -F -d "$root/work-data" "$out/work.ext4"
  rm -r -- "$root/work-data"
  # The cpio archive preserves the root directory mode. The model runs as an unprivileged UID.
  chmod 0755 "$root"
  touch "$root/etc/aios-qemu-ramdisk"
  mknod -m 600 "$root/dev/sda1" b 8 1
  (cd "$root" && find . -print0 | cpio --null -o --format=newc --owner=0:0) | gzip > "$out/document-init.cpio.gz"
  rm "$root/etc/aios-qemu-ramdisk" "$root/dev/sda1"
  truncate -s 16M "$out/system.ext4"
  mkfs.ext4 -q -F -d "$root" "$out/system.ext4"
  disk="$out/split.raw"
  truncate -s 34M "$disk"
  parted -s "$disk" mklabel msdos \
    mkpart primary ext4 1MiB 17MiB mkpart primary ext4 17MiB 33MiB
  dd if="$out/system.ext4" of="$disk" bs=1M seek=1 conv=notrunc status=none
  dd if="$out/work.ext4" of="$disk" bs=1M seek=17 conv=notrunc status=none
  exit
fi
if [[ ${3:-} == disk ]]; then
  truncate -s 48M "$out/starter.raw"
  mkfs.ext4 -q -F -d "$root" "$out/starter.raw"
  exit
fi
(cd "$root" && find . -print0 | cpio --null -o --format=newc --owner=0:0) | gzip > "$out/early-init.cpio.gz"
vm=(qemu-system-aarch64 -machine virt,gic-version=3 -cpu max -m 1024M -nic none \
  -display none -monitor none -serial stdio -kernel "$kernel" -initrd "$out/early-init.cpio.gz" \
  -append 'earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1')
if [[ ${3:-} == pstore ]]; then
  dtb="$out/pstore.dtb"
  "${vm[@]}" -machine "dumpdtb=$dtb"
  node=/reserved-memory/ramoops@70000000
  fdtput -p -c "$dtb" "$node"
  fdtput -t x "$dtb" /reserved-memory '#address-cells' 2
  fdtput -t x "$dtb" /reserved-memory '#size-cells' 2
  fdtput -t x "$dtb" /reserved-memory ranges
  fdtput -t s "$dtb" "$node" compatible ramoops
  fdtput -t x "$dtb" "$node" reg 0 70000000 0 200000
  fdtput -t x "$dtb" "$node" pmsg-size 200000
  timeout 45s "${vm[@]}" -dtb "$dtb" > "$out/console.log" 2>&1
  python3 - "$out/console.log" <<'PY'
import sys
from pathlib import Path

log = Path(sys.argv[1]).read_text(errors="replace")
assert log.count("AIOS_EARLY_INIT {") == 2, log[-4000:]
assert log.count("AIOS_PSTORE_WRITTEN") == log.count("AIOS_PSTORE_RECOVERED") == 1, log[-4000:]
assert log.index("AIOS_PSTORE_WRITTEN") < log.index("AIOS_PSTORE_RECOVERED")
print("AIOS recovered its pmsg boot record after guest reboot")
PY
  exit
fi
vm+=(-no-reboot)
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
