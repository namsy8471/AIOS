#!/usr/bin/env bash
set -euo pipefail
kernel=${1:?Pass a readable x86_64 Linux kernel image}
mkdir -p build
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/tmp" "$root/dev"
cargo build --locked --release --target x86_64-unknown-linux-musl
cp target/x86_64-unknown-linux-musl/release/aios "$root/init"
# The kernel opens /dev/console before launching PID 1.
sudo mknod "$root/dev/console" c 5 1
(cd "$root" && find . -print0 | cpio --null -o --format=newc --owner=0:0) | gzip > build/initramfs.gz
accelerator=${2:-tcg}
echo "Booting Linux with QEMU accelerator $accelerator"
timeout 60s qemu-system-x86_64 -accel "$accelerator" -m 256M -display none -serial stdio -monitor none -no-reboot \
  -kernel "$kernel" -initrd build/initramfs.gz -append 'console=ttyS0 rdinit=/init panic=1' | tee build/serial.log
grep -Fxq 'AIOS_BOOT_OK pid=1' < <(tr -d '\r' < build/serial.log)
