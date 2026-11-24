#!/usr/bin/env bash
set -euo pipefail
stage=$(mktemp -d)
container=
cleanup() {
  if [[ -n "$container" ]]; then docker rm "$container" >/dev/null; fi
  sudo rm -rf -- "$stage"
}
trap cleanup EXIT
mkdir -p build/runtime "$stage/media/live" "$stage/media/boot/grub" "$stage/root"
cargo build --locked --release
install target/release/aios build/runtime-aios
# Restrict the build context to the three image inputs.
mkdir -p "$stage/context/build"
cp -r runtime "$stage/context/"
cp build/runtime-aios "$stage/context/build/"
docker build -t aios-runtime -f scripts/runtime.Dockerfile "$stage/context"
container=$(docker create aios-runtime)
docker export "$container" | sudo tar -xpf - -C "$stage/root"
sudo install -m 0644 "$stage"/root/boot/vmlinuz-* "$stage/media/live/vmlinuz"
sudo install -m 0644 "$stage"/root/boot/initrd.img-* "$stage/media/live/initrd.img"
sudo mksquashfs "$stage/root" "$stage/media/live/filesystem.squashfs" -comp lz4 -noappend -no-progress -e boot
cat > "$stage/media/boot/grub/grub.cfg" <<'GRUB'
set timeout=0
menuentry "AIOS document runtime" {
  linux /live/vmlinuz boot=live console=tty0 console=ttyS0,115200 lsm=landlock panic=5
  initrd /live/initrd.img
}
GRUB
grub-mkrescue -o build/runtime/aios-runtime.iso "$stage/media"
(cd build/runtime && sha256sum aios-runtime.iso > SHA256SUMS)
