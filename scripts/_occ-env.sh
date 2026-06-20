#!/usr/bin/env bash
# 公共环境：让 FreeCAD 始终加载本地可改、带调试符号的 OCCT（occt/install/debug）。
# 被其它脚本 source。路径相对脚本位置自动推算，整个 freecad/ 目录可随意挪。
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export FREECAD_WS="$(cd "$HERE/.." && pwd)"          # = .../freecad
export FC_DIR="$FREECAD_WS/FreeCAD"                  # FreeCAD 源码/构建（pixi 环境在这）
export OCC_DIR="$FREECAD_WS/occt"                     # OCCT 源码
export OCC_BUILD_DIR="$OCC_DIR/build/debug"           # OCCT Debug 构建目录
export OCC_INSTALL_DIR="$OCC_DIR/install/debug"       # OCCT Debug 安装目录
export LOCAL_OCC_LIB="$OCC_INSTALL_DIR/lib"           # 本地 Debug OCCT 库
export PIXI_ENV_DIR="$FC_DIR/.pixi/envs/default"      # FreeCAD 的锁定工具链/依赖环境

if [ ! -d "$LOCAL_OCC_LIB" ]; then
  echo "[!] 找不到本地 debug OCCT: $LOCAL_OCC_LIB" >&2
  echo "    先编 occt（见 rebuild-occ.sh）" >&2
fi
