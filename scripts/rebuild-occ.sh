#!/usr/bin/env bash
# 改了 occt/src 后，重编 + 安装到 occt/install/debug；FreeCAD 下次启动即用新逻辑。
# Unix Makefiles 的 install 目标会先重编有变动的目标再安装（增量，只编你改的）。
#   用法： scripts/rebuild-occ.sh [并行数，默认 8]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_occ-env.sh"
JOBS="${1:-8}"

if [ ! -s "$OCC_BUILD_DIR/compile_commands.json" ] \
  || ! grep -q '^CMAKE_EXPORT_COMPILE_COMMANDS:BOOL=ON$' "$OCC_BUILD_DIR/CMakeCache.txt"; then
  "$SCRIPT_DIR/configure-occt.sh"
fi

cd "$FC_DIR"   # 在 pixi 环境里编（clang/工具链都在这）
echo "[*] 增量重编 occt 并安装到 install/debug （-j${JOBS}）…"
pixi run --frozen -- cmake --build "$OCC_BUILD_DIR" --target install -j "$JOBS"
echo "[✓] 完成。直接用 scripts/fc-cmd.sh / fc-gui.sh / fc-lldb.sh 即可跑到新逻辑。"
