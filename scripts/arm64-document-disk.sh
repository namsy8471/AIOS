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
cp /boot/{vmlinuz-virt,initramfs-virt} scripts/arm64-console.sh "$bundle/"
cp "$stage/work.raw" "$bundle/starter.raw"
(cd "$bundle" && sha256sum vmlinuz-virt initramfs-virt starter.raw arm64-console.sh > SHA256SUMS)
timeout 240s python3 tests/arm64_document_disk.py "$bundle/arm64-console.sh" "$stage/work.raw"
debugfs -R "dump /work/note.txt $stage/offline.txt" "$stage/work.raw"
printf '작업 기록\n재부팅 검증\n전원 중단 검증' | cmp - "$stage/offline.txt"
echo 'Offline ext4 document bytes verified'
