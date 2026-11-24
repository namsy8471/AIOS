#!/usr/bin/env bash
# Build and boot the same optical image with BIOS and UEFI firmware.
set -euo pipefail
kernel=${1:?Pass the kernel image used for the initramfs}
initramfs=${2:?Pass the tested initramfs}
out=build/firmware
mkdir -p "$out"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/iso/boot/grub"
cp "$kernel" "$stage/iso/boot/vmlinuz"
cp "$initramfs" "$stage/iso/boot/initramfs.gz"
cat > "$stage/iso/boot/grub/grub.cfg" <<'GRUB'
serial --unit=0 --speed=115200
terminal_output console serial
set timeout=0
set default=0
menuentry 'AIOS boot check' {
    echo "AIOS_GRUB_PLATFORM=$grub_platform"
    linux /boot/vmlinuz console=tty0 console=ttyS0,115200 rdinit=/init panic=1
    initrd /boot/initramfs.gz
}
GRUB
grub-mkrescue -o "$stage/aios-boot.iso" "$stage/iso"

boot_iso() {
    local platform=$1
    shift
    local log="$stage/$platform.log"
    timeout 90s qemu-system-x86_64 -accel tcg -machine q35 -m 512M \
        -display none -serial stdio -monitor none -nic none -no-reboot \
        -boot order=d,strict=on -cdrom "$stage/aios-boot.iso" "$@" > "$log" 2>&1 || {
            tail -n 40 "$log" >&2
            return 1
        }
    tr -d '\r' < "$log" > "$out/$platform.log"
    grep -F "AIOS_GRUB_PLATFORM=$platform" "$out/$platform.log"
    grep -Fx 'AIOS: save verified; modal and stale requests stopped' "$out/$platform.log"
    grep -Fx 'AIOS_BOOT_OK pid=1' "$out/$platform.log"
}
boot_iso pc
cp /usr/share/OVMF/OVMF_VARS.fd "$stage/vars.fd"
boot_iso efi -drive if=pflash,format=raw,unit=0,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
             -drive "if=pflash,format=raw,unit=1,file=$stage/vars.fd"
mv "$stage/aios-boot.iso" "$out/aios-boot.iso"
(cd "$out" && sha256sum aios-boot.iso > SHA256SUMS)
