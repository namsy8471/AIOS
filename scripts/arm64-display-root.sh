#!/usr/bin/env bash
# Build the display runtime and its library closure for an ARM64 root filesystem.
set -euo pipefail
root=${1:?Pass the display runtime root directory}
fonts="$root/usr/share/aios"
mkdir -p "$root/usr/bin" "$fonts"

cc -O2 -Wall -Wextra $(pkg-config --cflags libdrm freetype2) src/display-frame.c \
  -o "$root/usr/bin/display-frame" $(pkg-config --libs libdrm freetype2)

font_source=https://raw.githubusercontent.com/google/fonts/16680f8688ffcd467d2eb2146a9ce0343404581d/ofl/nanumgothic
curl -fsSL --retry 3 "$font_source/NanumGothic-Regular.ttf" -o "$fonts/NanumGothic-Regular.ttf"
(cd "$fonts" && echo '76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31  NanumGothic-Regular.ttf' | sha256sum -c -)
curl -fsSL --retry 3 "$font_source/OFL.txt" -o "$fonts/OFL.txt"

libraries=$(ldd "$root/usr/bin/display-frame")
if [[ $libraries == *'not found'* ]]; then
  printf '%s\n' "$libraries" >&2
  exit 1
fi
while IFS= read -r library; do
  install -Dm755 "$library" "$root$library"
done < <(awk '{for (i=1; i<=NF; i++) if ($i ~ /^\//) print $i}' <<< "$libraries" | sort -u)
