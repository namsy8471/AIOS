#!/usr/bin/env bash
set -euo pipefail
bundle=build/runtime
stage=$(mktemp -d)
mkdir "$stage/mount"
cleanup() {
    if mountpoint -q "$stage/mount"; then sudo umount "$stage/mount"; fi
    rm -rf -- "$stage"
}
trap cleanup EXIT
truncate -s 256M "$stage/starter.raw"
mkfs.btrfs -q -L AIOS-DATA "$stage/starter.raw"
sudo mount -o loop "$stage/starter.raw" "$stage/mount"
sudo btrfs subvolume create "$stage/mount/documents"
printf 'AIOS 첫 문서' | sudo tee "$stage/mount/documents/note.txt" >/dev/null
sudo umount "$stage/mount"
xz -1 -c "$stage/starter.raw" > "$bundle/starter.raw.xz"
cp scripts/{aios_mvp,model_mvp}.py "$bundle/"
(cd "$bundle" && sha256sum aios-runtime.iso starter.raw.xz aios_mvp.py model_mvp.py > SHA256SUMS)
