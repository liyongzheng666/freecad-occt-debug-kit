#!/usr/bin/env bash
# 在 lldb 里调试 FreeCADCmd，已把【本地 debug occt】喂给被调试进程。
#   用法： scripts/fc-lldb.sh 你的脚本.py
#   进 lldb 后常用：
#     (lldb) breakpoint set --method Add --shlib libTKFillet.7.8.1.dylib
#     (lldb) b BRepFilletAPI_MakeFillet.cxx:106
#     (lldb) b ChFi3d_Builder::PerformIntersectionAtEnd     # 圆角真正翻车处
#     (lldb) run
#     (lldb) bt / frame variable / p R1
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_occ-env.sh"
ARGS=()
for a in "$@"; do
  if [ -e "$a" ]; then a="$(cd "$(dirname "$a")" && pwd)/$(basename "$a")"; fi
  ARGS+=("$a")
done
cd "$FC_DIR"
exec pixi run --frozen -- lldb \
  -o "settings set target.env-vars DYLD_LIBRARY_PATH=$LOCAL_OCC_LIB" \
  -- build/debug/bin/FreeCADCmd "${ARGS[@]}"
