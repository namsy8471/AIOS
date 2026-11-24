#!/usr/bin/env bash
set -euo pipefail
kernel=${1:?Pass a readable Linux kernel image for the host architecture}
arch=$(uname -m)
case "$arch" in
  x86_64) machine=(); memory=256M; console=ttyS0 ;;
  aarch64) machine=(-machine virt -cpu cortex-a53); memory=128M; console=ttyAMA0 ;;
  *) echo "Unsupported test architecture: $arch" >&2; exit 1 ;;
esac
mkdir -p build
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/tmp" "$root/dev" "$root/usr/bin" "$root/work"
cargo build --locked --release --target "$arch-unknown-linux-musl"
cp "target/$arch-unknown-linux-musl/release/aios" "$root/init"
strip "$root/init"
ln "$root/init" "$root/usr/bin/aios"
# The kernel opens /dev/console before launching PID 1.
sudo mknod "$root/dev/console" c 5 1
sudo mknod -m 666 "$root/dev/null" c 1 3
(cd "$root" && find . -print0 | cpio --null -o --format=newc --owner=0:0) | gzip > build/initramfs.gz
accelerator=${2:-tcg}
echo "Booting Linux with QEMU accelerator $accelerator"
timeout 60s "qemu-system-$arch" "${machine[@]}" -accel "$accelerator" -m "$memory" -display none -serial stdio -monitor none -no-reboot \
  -kernel "$kernel" -initrd build/initramfs.gz -append "console=$console rdinit=/init panic=1" | tee build/serial.log
grep -Fxq 'AIOS_BOOT_OK pid=1' < <(tr -d '\r' < build/serial.log)
printf 'arch=%s guest_ram=%s init_bytes=%s initramfs_gzip_bytes=%s kernel_bytes=%s\n' \
  "$arch" "$memory" "$(stat -c %s "$root/init")" "$(stat -c %s build/initramfs.gz)" "$(stat -Lc %s "$kernel")"
