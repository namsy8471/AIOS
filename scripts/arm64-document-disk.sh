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
cc -O2 -Wall -Wextra $(pkg-config --cflags libdrm freetype2) src/display-frame.c \
  -o "$stage/root/usr/bin/display-frame" $(pkg-config --libs libdrm freetype2)
fonts="$stage/root/usr/share/aios"
mkdir -p "$fonts"
font_source=https://raw.githubusercontent.com/google/fonts/16680f8688ffcd467d2eb2146a9ce0343404581d/ofl/nanumgothic
curl -fsSL --retry 3 "$font_source/NanumGothic-Regular.ttf" -o "$fonts/NanumGothic-Regular.ttf"
(cd "$fonts" && echo '76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31  NanumGothic-Regular.ttf' | sha256sum -c -)
curl -fsSL --retry 3 "$font_source/OFL.txt" -o "$fonts/OFL.txt"
while IFS= read -r library; do
  install -Dm755 "$library" "$stage/root$library"
done < <(ldd "$stage/root/usr/bin/display-frame" | awk '{for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i}' | sort -u)
mkdir "$stage/root/dev/dri" "$stage/root/dev/input"
mknod -m 600 "$stage/root/dev/dri/card0" c 226 0
mknod -m 600 "$stage/root/dev/input/event0" c 13 64
truncate -s 48M "$stage/display.raw"
mkfs.ext4 -q -F -d "$stage/root" "$stage/display.raw"
if [[ ${AIOS_PACKAGE_DISPLAY:-0} == 1 ]]; then
  package=build/arm64-display-package
  mkdir -p "$package"
  cp "$bundle"/{vmlinuz-virt,arm64_model.py,model_mvp.py} "$package/"
  cp "$stage/display-initramfs" "$package/display-initramfs"
  cp "$stage/display.raw" "$package/display-starter.raw"
fi
timeout 90s python3 tests/arm64_drm.py "$bundle" "$stage/display-initramfs" "$stage/display.raw" "$display"
debugfs -R "dump /work/note.txt $stage/touch-saved.txt" "$stage/display.raw"
printf '작업 기록\n우유' | cmp - "$stage/touch-saved.txt"
