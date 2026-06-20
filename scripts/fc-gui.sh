#!/usr/bin/env bash
# 用【本地 debug occt】启动 FreeCAD GUI（会弹窗口）。
#   用法： scripts/fc-gui.sh [可选 .FCStd 文件]
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_occ-env.sh"
ARGS=()
for a in "$@"; do
  if [ -e "$a" ]; then a="$(cd "$(dirname "$a")" && pwd)/$(basename "$a")"; fi
  ARGS+=("$a")
done
cd "$FC_DIR"
exec pixi run --frozen -- env DYLD_LIBRARY_PATH="$LOCAL_OCC_LIB" \
  build/debug/bin/FreeCAD "${ARGS[@]}"
