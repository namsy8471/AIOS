#!/usr/bin/env bash
# Assemble an unsigned reference image and boot its extracted payloads in QEMU.
set -euo pipefail
reference=${1:?Pass the community recovery image}
probe=${2:?Pass the pstore probe output directory}
out=${3:?Pass a new output directory}
mkdir -p "$out"
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT

unpack_bootimg --boot_img "$reference" --out "$stage/reference"
# Ubuntu's packaged mkbootimg imports a missing GKI module. Use AOSP's
# standalone v2 implementation and verify the exact bytes before running it.
curl -fsSL --retry 3 'https://android.googlesource.com/platform/system/core/+/f74ff74475494e25ab27a507ff55bfefb78ff905/mkbootimg/mkbootimg.py?format=TEXT' \
  | base64 -d > "$stage/mkbootimg.py"
(cd "$stage" && echo '9601797b2d1a8ef6494ebd190809479b38bbde38f76709ecc9293b96ab1be65d  mkbootimg.py' | sha256sum -c -)
python3 "$stage/mkbootimg.py" --header_version 2 --pagesize 4096 --base 0 \
  --kernel_offset 0x8000 --ramdisk_offset 0x02000000 \
  --tags_offset 0x01e00000 --dtb_offset 0x01f00000 \
  --kernel "$stage/reference/kernel" --ramdisk "$probe/early-init.cpio.gz" \
  --recovery_dtbo "$stage/reference/recovery_dtbo" --dtb "$stage/reference/dtb" \
  --output "$out/aios-flip4-reference-unsigned.img"

image="$out/aios-flip4-reference-unsigned.img"
python3 scripts/inspect-flip4-boot-image.py "$image" > "$out/layout.json"
unpack_bootimg --boot_img "$image" --out "$stage/diagnostic"
for component in kernel recovery_dtbo dtb; do
  cmp "$stage/reference/$component" "$stage/diagnostic/$component"
done
cmp "$probe/early-init.cpio.gz" "$stage/diagnostic/ramdisk"

# QEMU supplies its own board tree with a reserved ramoops RAM node.
timeout 45s qemu-system-aarch64 -machine virt,gic-version=3 -cpu max -m 1024M -nic none \
  -display none -monitor none -serial stdio -kernel "$stage/diagnostic/kernel" \
  -initrd "$stage/diagnostic/ramdisk" -dtb "$probe/pstore.dtb" \
  -append 'earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1' \
  > "$out/console.log" 2>&1
tr -d '\r' < "$out/console.log" | grep -xE 'AIOS_PSTORE_WRITTEN|AIOS_PSTORE_RECOVERED' > "$stage/markers"
printf '%s\n' AIOS_PSTORE_WRITTEN AIOS_PSTORE_RECOVERED | cmp - "$stage/markers"
(cd "$out" && sha256sum aios-flip4-reference-unsigned.img layout.json console.log > SHA256SUMS)
