#!/usr/bin/env bash
# Prepare regular-file ext4 volumes for the Flip4 document initramfs.
set -euo pipefail
source_model=${1:?Pass an existing ext4 model image}
out=${2:?Pass a new output directory}
work_partition=${3:?Pass the intended Linux work partition name}
model_partition=${4:?Pass the intended Linux model partition name}
[[ -f $source_model && $work_partition =~ ^[a-zA-Z0-9]+$ && $model_partition =~ ^[a-zA-Z0-9]+$ ]]
[[ $work_partition != "$model_partition" ]]
mkdir "$out"
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
printf '장보기' > "$stage/note.txt"
printf 'AIOS document volume v1\n' > "$stage/.aios-work-volume"
truncate -s 16M "$out/work.ext4"
mkfs.ext4 -q -F -L AIOS_WORK -d "$stage" "$out/work.ext4"
cp --sparse=always "$source_model" "$out/model.ext4"
e2fsck -fn "$out/model.ext4"
model_uuid=$(cat /proc/sys/kernel/random/uuid)
tune2fs -L AIOS_MODEL -U "$model_uuid" "$out/model.ext4"
work_uuid=$(blkid -s UUID -o value "$out/work.ext4")
printf 'work=%s:%s\nmodel=%s:%s\n' "$work_partition" "$work_uuid" "$model_partition" "$model_uuid" > "$out/volumes.conf"
