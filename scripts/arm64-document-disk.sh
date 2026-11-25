#!/usr/bin/env bash
set -euo pipefail
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
mkdir -p "$stage/root"/{etc,dev,proc,sys,run,tmp,work,usr/bin,sbin}
cp target/aarch64-unknown-linux-musl/release/aios "$stage/root/init"
strip "$stage/root/init"
ln "$stage/root/init" "$stage/root/usr/bin/aios"
ln -s /init "$stage/root/sbin/init"
touch "$stage/root/etc/aios-document-console"
printf '작업 기록' > "$stage/root/work/note.txt"
truncate -s 48M "$stage/work.raw"
mkfs.ext4 -q -F -d "$stage/root" "$stage/work.raw"
bundle=build/arm64-console
mkdir -p "$bundle"
install -m 0644 /boot/vmlinuz-virt scripts/{arm64-console.sh,arm64_model.py,model_mvp.py} "$bundle/"
# This board boots an ext4 root over virtio. Select modules for the packaged
# guest kernel, independently of the kernel running the build container.
modules=(/lib/modules/*-virt)
[[ ${#modules[@]} -eq 1 && -d ${modules[0]} ]]
mkinitfs -F 'base virtio ext4' -o "$stage/initramfs-virt" "${modules[0]##*/}"
install -m 0644 "$stage/initramfs-virt" "$bundle/initramfs-virt"
printf 'ARM64 initramfs bytes: generic=%s console=%s\n' \
  "$(stat -Lc %s /boot/initramfs-virt)" "$(stat -c %s "$bundle/initramfs-virt")"
cp "$stage/work.raw" "$bundle/starter.raw"
(cd "$bundle" && sha256sum vmlinuz-virt initramfs-virt starter.raw arm64-console.sh arm64_model.py model_mvp.py > SHA256SUMS)
timeout 240s python3 tests/arm64_document_disk.py "$bundle/arm64-console.sh" "$stage/work.raw"
debugfs -R "dump /work/note.txt $stage/offline.txt" "$stage/work.raw"
printf '작업 기록\n재부팅 검증\n전원 중단 검증' | cmp - "$stage/offline.txt"
echo 'Offline ext4 document bytes verified'

display=build/arm64-display
mkdir -p "$display" "$stage/features"
cat > "$stage/features/display.modules" <<'EOF'
kernel/drivers/gpu/drm
kernel/drivers/input/evdev.ko*
kernel/drivers/virtio/virtio_input.ko*
EOF
mkinitfs -P "$stage/features" -F 'base virtio ext4 display' -o "$stage/display-initramfs" "${modules[0]##*/}"
cc -Wall -Wextra $(pkg-config --cflags libdrm) tests/display_route.c -o "$stage/display-route-test"
"$stage/display-route-test"
bash scripts/arm64-display-root.sh "$stage/root"
truncate -s 48M "$stage/display.raw"
mkfs.ext4 -q -F -d "$stage/root" "$stage/display.raw"
cp "$stage/display.raw" "$stage/multitouch.raw"
cp scripts/arm64_touch.py "$bundle/"
if [[ ${AIOS_PACKAGE_DISPLAY:-0} == 1 ]]; then
  package=build/arm64-display-package
  mkdir -p "$package"
  cp "$bundle"/{vmlinuz-virt,arm64_model.py,arm64_touch.py,model_mvp.py} "$package/"
  install -m 0644 "$stage/display-initramfs" "$package/display-initramfs"
  cp "$stage/display.raw" "$package/display-starter.raw"
fi
timeout 90s python3 tests/arm64_drm.py "$bundle" "$stage/display-initramfs" "$stage/display.raw" "$display"
debugfs -R "dump /work/note.txt $stage/touch-saved.txt" "$stage/display.raw"
printf '작업 기록\n우유' | cmp - "$stage/touch-saved.txt"
mkdir -p "$display/multitouch"
timeout 90s python3 tests/arm64_drm.py "$bundle" "$stage/display-initramfs" "$stage/multitouch.raw" "$display/multitouch" --multitouch
