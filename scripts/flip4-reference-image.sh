#!/usr/bin/env bash
# Assemble an unsigned reference image and boot its extracted payloads in QEMU.
set -euo pipefail
reference=${1:?Pass the community recovery image}
probe=${2:?Pass the pstore probe output directory}
out=${3:?Pass a new output directory}
split=${4:?Pass the split-disk build output}
bundle=${5:?Pass the reference kernel and test disk bundle}
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

assemble "$split/document-init.cpio.gz" "$out/aios-flip4-document-reference-unsigned.img" \
  "$out/document-layout.json" "$stage/document"
cp "$bundle/split-starter.raw" "$stage/document-work.raw"
if ! timeout 90s python3 tests/flip4_split_disk.py "$bundle" "$stage/document-work.raw" "$stage/document" \
  > "$out/document-proof.json"; then
  tail -n 40 "$stage"/console-*.log >&2
  exit 1
fi
cp "$stage/console-1.log" "$out/document-first-boot.log"
cp "$stage/console-2.log" "$out/document-second-boot.log"
(cd "$out" && sha256sum *.img *.json *.log > SHA256SUMS)
