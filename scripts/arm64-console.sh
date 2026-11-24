#!/usr/bin/env bash
set -euo pipefail
bundle=$(cd -- "$(dirname -- "$0")" && pwd)
disk=${1:?Pass the path of a writable copy of starter.raw}
exec qemu-system-aarch64 -machine virt -cpu cortex-a53 -m 128M -nic none \
  -display none -monitor none -serial stdio -no-reboot \
  -kernel "$bundle/vmlinuz-virt" -initrd "$bundle/initramfs-virt" \
  -append 'console=ttyAMA0 root=/dev/vda rootfstype=ext4 rootflags=rw rw panic=1' \
  -drive "file=${disk//,/,,},if=virtio,format=raw,cache=none"
