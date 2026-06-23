#!/usr/bin/env bash
# =====================================================================
# Build occ-debug-mesh against the local debug OCCT, using FreeCAD's locked
# Pixi toolchain (same clang/ABI as the debugged process). Idempotent.
#
#   Usage: scripts/build-occ-debug-mesh.sh [JOBS]
# =====================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_occ-env.sh"

TOOL_DIR="$FREECAD_WS/tools/occ-debug-mesh"
BUILD_DIR="$TOOL_DIR/build"
JOBS="${1:-8}"

cd "$FC_DIR"
pixi run --frozen -- cmake \
  -S "$TOOL_DIR" \
  -B "$BUILD_DIR" \
  -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE:STRING=Debug \
  -DOpenCASCADE_DIR:PATH="$OCC_INSTALL_DIR/lib/cmake/opencascade" \
  -DCMAKE_CXX_COMPILER:FILEPATH="$PIXI_ENV_DIR/bin/arm64-apple-darwin20.0.0-clang++" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS:BOOL=ON

pixi run --frozen -- cmake --build "$BUILD_DIR" -j "$JOBS"
echo "[ok] occ-debug-mesh -> $BUILD_DIR/occ-debug-mesh"
