#!/usr/bin/env bash
# 用【本地 debug occt】跑 FreeCAD 控制台版（做 harness/测试用，无 GUI）。
#   用法： scripts/fc-cmd.sh 你的脚本.py [参数...]
#         scripts/fc-cmd.sh -c "import Part; print(Part.makeBox(1,1,1).Volume)"
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_occ-env.sh"
# 先把“存在的文件”参数转成绝对路径（脚本随后会 cd 进 FreeCAD/，相对路径会失效）
ARGS=()
for a in "$@"; do
  if [ -e "$a" ]; then a="$(cd "$(dirname "$a")" && pwd)/$(basename "$a")"; fi
  ARGS+=("$a")
done
cd "$FC_DIR"
exec pixi run --frozen -- env DYLD_LIBRARY_PATH="$LOCAL_OCC_LIB" \
  build/debug/bin/FreeCADCmd "${ARGS[@]}"
