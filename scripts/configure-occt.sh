#!/usr/bin/env bash
# Configure the sibling OCCT checkout with FreeCAD's locked Pixi toolchain.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_occ-env.sh"

cd "$FC_DIR"
pixi run --frozen -- cmake \
  -S "$OCC_DIR" \
  -B "$OCC_BUILD_DIR" \
  -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE:STRING=Debug \
  -DCMAKE_INSTALL_PREFIX:PATH="$OCC_INSTALL_DIR" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS:BOOL=ON \
  -DCMAKE_C_COMPILER:FILEPATH="$PIXI_ENV_DIR/bin/arm64-apple-darwin20.0.0-clang" \
  -DCMAKE_CXX_COMPILER:FILEPATH="$PIXI_ENV_DIR/bin/arm64-apple-darwin20.0.0-clang++" \
  -DCMAKE_C_FLAGS_DEBUG:STRING="-g -O0 -fno-omit-frame-pointer" \
  -DCMAKE_CXX_FLAGS_DEBUG:STRING="-g -O0 -fno-omit-frame-pointer"

echo "[ok] OCCT configured: $OCC_BUILD_DIR"
echo "[ok] Compilation database: $OCC_BUILD_DIR/compile_commands.json"
