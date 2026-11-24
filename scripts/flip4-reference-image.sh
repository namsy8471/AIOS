#!/usr/bin/env bash
# Assemble an unsigned reference image and boot its extracted payloads in QEMU.
set -euo pipefail
mode=${1:-}
if [[ $mode == --driver-image || $mode == --board-image ]]; then
  reference=${2:?Pass the community recovery image}
  document_ramdisk=${3:?Pass the extracted AIOS document ramdisk}
  out=${4:?Pass a new output directory}
else
  reference=${1:?Pass the community recovery image}
  probe=${2:?Pass the pstore probe output directory}
  out=${3:?Pass a new output directory}
  split=${4:?Pass the split-disk build output}
  bundle=${5:?Pass the reference kernel and test disk bundle}
  document_ramdisk="$split/document-init.cpio.gz"
fi
mkdir -p "$out"
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT

unpack_bootimg --boot_img "$reference" --out "$stage/reference"
# Ubuntu's packaged mkbootimg imports a missing GKI module. Use AOSP's
# standalone v2 implementation and verify the exact bytes before running it.
curl -fsSL --retry 3 'https://android.googlesource.com/platform/system/tools/mkbootimg/+/808d42e197506319ee65eb078d3defd9602e2ac2/mkbootimg.py?format=TEXT' \
  | base64 -d > "$stage/mkbootimg.py"
(cd "$stage" && echo '629bec961280743b9342c99dfef4ff5f1722d82d949e7855a8b16b2a03b8fc7a  mkbootimg.py' | sha256sum -c -)
assemble() {
  local ramdisk=$1 image=$2 layout=$3 extracted=$4
  python3 "$stage/mkbootimg.py" --header_version 2 --pagesize 4096 --base 0 \
    --kernel_offset 0x8000 --ramdisk_offset 0x02000000 \
    --tags_offset 0x01e00000 --dtb_offset 0x01f00000 \
    --kernel "$stage/reference/kernel" --ramdisk "$ramdisk" \
    --recovery_dtbo "$stage/reference/recovery_dtbo" --dtb "$stage/reference/dtb" \
    --output "$image"
  python3 scripts/inspect-flip4-boot-image.py "$image" > "$layout"
  unpack_bootimg --boot_img "$image" --out "$extracted"
  for component in kernel recovery_dtbo dtb; do
    cmp "$stage/reference/$component" "$extracted/$component"
  done
  cmp "$ramdisk" "$extracted/ramdisk"
}

assemble_driver_image() {
  local destination=$1 layout=$2
  shift 2
  mkdir -p "$destination"
  python3 tests/flip4_module_probe.py "$reference" "$stage/module-overlay" --overlay "$@"
  # The kernel unpacks both members into the same initramfs tree.
  cat "$document_ramdisk" "$stage/module-overlay/drivers.cpio.gz" > "$stage/document-with-drivers.cpio.gz"
  assemble "$stage/document-with-drivers.cpio.gz" "$destination/document-with-drivers.img" \
    "$layout" "$destination/payload"
  cp "$stage/module-overlay/order.txt" "$destination/order.txt"
}

if [[ $mode == --board-image ]]; then
  assemble_driver_image "$out" "$out/layout.json" --board-overlay
  python3 scripts/flip4_board.py "$out/payload" "$out/order.txt" "$stage/module-overlay/recovery-files.txt" "$out"
  python3 scripts/inspect-phone-kernel.py "$out/payload/kernel" > "$out/kernel.json"
  exit
fi

if [[ $mode == --driver-image ]]; then
  assemble_driver_image "$out" "$out/layout.json"
  exit
fi

assemble "$probe/early-init.cpio.gz" "$out/aios-flip4-reference-unsigned.img" \
  "$out/layout.json" "$stage/diagnostic"

# QEMU supplies its own board tree with a reserved ramoops RAM node.
timeout 45s qemu-system-aarch64 -machine virt,gic-version=3 -cpu max -m 1024M -nic none \
  -display none -monitor none -serial stdio -kernel "$stage/diagnostic/kernel" \
  -initrd "$stage/diagnostic/ramdisk" -dtb "$probe/pstore.dtb" \
  -append 'earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1' \
  > "$out/console.log" 2>&1
tr -d '\r' < "$out/console.log" | grep -xE 'AIOS_PSTORE_WRITTEN|AIOS_PSTORE_RECOVERED' > "$stage/markers"
printf '%s\n' AIOS_PSTORE_WRITTEN AIOS_PSTORE_RECOVERED | cmp - "$stage/markers"

assemble "$document_ramdisk" "$out/aios-flip4-document-reference-unsigned.img" \
  "$out/document-layout.json" "$stage/document"
cp "$bundle/split-starter.raw" "$stage/document-work.raw"
if ! timeout 90s python3 tests/flip4_split_disk.py "$bundle" "$stage/document-work.raw" "$stage/document" \
  > "$out/document-proof.json"; then
  tail -n 40 "$stage"/console-*.log >&2
  exit 1
fi
cp "$stage/console-1.log" "$out/document-first-boot.log"
cp "$stage/console-2.log" "$out/document-second-boot.log"

assemble_driver_image "$stage/document-with-drivers" "$out/document-driver-layout.json"
mkdir "$stage/driver-test"
cp "$bundle/split-starter.raw" "$stage/driver-test/work.raw"
if ! timeout 120s python3 tests/flip4_split_disk.py "$bundle" "$stage/driver-test/work.raw" \
  "$stage/document-with-drivers/payload" --driver-order "$stage/document-with-drivers/order.txt" \
  > "$out/document-driver-proof.json"; then
  tail -n 60 "$stage/driver-test"/console-*.log >&2
  exit 1
fi
cp "$stage/driver-test/console-1.log" "$out/document-driver-first-boot.log"
cp "$stage/driver-test/console-2.log" "$out/document-driver-second-boot.log"
(cd "$out" && sha256sum *.img *.json *.log > SHA256SUMS)
