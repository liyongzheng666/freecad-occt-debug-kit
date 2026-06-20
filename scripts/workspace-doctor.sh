#!/usr/bin/env bash
# Validate the local FreeCAD + OCCT development workspace without changing it.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_occ-env.sh"

errors=0
warnings=0

pass() { printf '[pass] %s\n' "$*"; }
warn() { printf '[warn] %s\n' "$*"; warnings=$((warnings + 1)); }
fail() { printf '[fail] %s\n' "$*"; errors=$((errors + 1)); }

check_file() {
  if [ -s "$1" ]; then pass "$2"; else fail "$2 ($1)"; fi
}

check_dir() {
  if [ -d "$1" ]; then pass "$2"; else fail "$2 ($1)"; fi
}

check_executable() {
  if [ -x "$1" ]; then pass "$2"; else fail "$2 ($1)"; fi
}

echo '== Workspace layout =='
check_dir "$FC_DIR/.git" 'FreeCAD Git repository'
check_dir "$OCC_DIR/.git" 'OCCT Git repository'
check_dir "$PIXI_ENV_DIR" 'Pixi environment'
check_dir "$OCC_BUILD_DIR" 'OCCT debug build directory'
check_dir "$OCC_INSTALL_DIR" 'OCCT debug install directory'

echo '== Build metadata =='
check_file "$FC_DIR/build/debug/compile_commands.json" 'FreeCAD compilation database'
check_file "$OCC_BUILD_DIR/compile_commands.json" 'OCCT compilation database'
check_file "$FREECAD_WS/.clangd" 'Workspace clangd routing configuration'

if grep -Fq 'FeatureFillet.cpp' "$FC_DIR/build/debug/compile_commands.json" 2>/dev/null; then
  pass 'FreeCAD CDB contains FeatureFillet.cpp'
else
  fail 'FreeCAD CDB contains FeatureFillet.cpp'
fi

if grep -Fq 'ChFi3d_Builder.cxx' "$OCC_BUILD_DIR/compile_commands.json" 2>/dev/null; then
  pass 'OCCT CDB contains ChFi3d_Builder.cxx'
else
  fail 'OCCT CDB contains ChFi3d_Builder.cxx'
fi

if grep -q '^CMAKE_EXPORT_COMPILE_COMMANDS:BOOL=ON$' "$OCC_BUILD_DIR/CMakeCache.txt" 2>/dev/null; then
  pass 'OCCT exports compile commands'
else
  fail 'OCCT exports compile commands'
fi

if grep -Fqx "OCC_LIBRARY:FILEPATH=$LOCAL_OCC_LIB/libTKernel.dylib" \
  "$FC_DIR/build/debug/CMakeCache.txt" 2>/dev/null; then
  pass 'FreeCAD links against the local OCCT installation'
else
  fail 'FreeCAD links against the local OCCT installation'
fi

if grep -Fqx "OCC_INCLUDE_DIR:FILEPATH=$OCC_INSTALL_DIR/include/opencascade" \
  "$FC_DIR/build/debug/CMakeCache.txt" 2>/dev/null; then
  pass 'FreeCAD indexes local OCCT headers'
else
  fail 'FreeCAD indexes local OCCT headers'
fi

echo '== Toolchain =='
check_executable /usr/bin/clangd 'Apple clangd'
check_executable "$PIXI_ENV_DIR/bin/arm64-apple-darwin20.0.0-clang++" 'Pixi C++ compiler'
check_executable "$FC_DIR/build/debug/bin/FreeCADCmd" 'FreeCADCmd debug executable'
check_file "$LOCAL_OCC_LIB/libTKFillet.7.8.1.dylib" 'Local debug libTKFillet'

if file "$FC_DIR/build/debug/bin/FreeCADCmd" "$LOCAL_OCC_LIB/libTKFillet.7.8.1.dylib" 2>/dev/null | grep -vq 'arm64'; then
  fail 'FreeCADCmd and libTKFillet are arm64'
else
  pass 'FreeCADCmd and libTKFillet are arm64'
fi

echo '== Configuration hygiene =='
if git -C "$FC_DIR" diff --quiet -- CMakePresets.json; then
  pass 'Shared FreeCAD CMakePresets.json is clean'
else
  fail 'Shared FreeCAD CMakePresets.json is clean'
fi

if git -C "$FC_DIR" check-ignore -q CMakeUserPresets.json; then
  pass 'Local CMakeUserPresets.json is ignored by FreeCAD Git'
else
  fail 'Local CMakeUserPresets.json is ignored by FreeCAD Git'
fi

if grep -Fq '/Users/allyhan/' "$FC_DIR/CMakePresets.json"; then
  fail 'Shared FreeCAD preset has no machine-specific path'
else
  pass 'Shared FreeCAD preset has no machine-specific path'
fi

if git -C "$OCC_DIR" symbolic-ref -q --short HEAD >/dev/null; then
  pass "OCCT is on branch $(git -C "$OCC_DIR" branch --show-current)"
else
  fail 'OCCT is on a named branch'
fi

echo '== Editor and debugger integration =='
CLANGD_EXTENSION=$(find "$HOME/.vscode/extensions" -maxdepth 1 \
  -type d -name 'llvm-vs-code-extensions.vscode-clangd-*' 2>/dev/null | sort | tail -n 1)
if [ -n "$CLANGD_EXTENSION" ]; then
  pass "VS Code clangd extension (${CLANGD_EXTENSION#$HOME/})"
else
  fail 'VS Code clangd extension'
fi

CODELLDB=$(find "$HOME/.vscode/extensions" -path '*/adapter/codelldb' -type f 2>/dev/null | sort | tail -n 1)
if [ -n "$CODELLDB" ] && [ -x "$CODELLDB" ]; then
  pass "CodeLLDB adapter (${CODELLDB#$HOME/})"
else
  fail 'CodeLLDB adapter'
fi
check_file "$SCRIPT_DIR/lldb_occt_formatters.py" 'OCCT LLDB formatter'
check_file "$FC_DIR/contrib/debugger/qt_pretty_printers_lldb.py" 'Qt LLDB formatter'

clangd_check() {
  local source_file=$1
  local cdb_dir=$2
  local label=$3
  local output
  output=$(/usr/bin/clangd --check="$source_file" --check-lines=1 \
    --compile-commands-dir="$cdb_dir" --log=info 2>&1)
  if grep -Fq 'All checks completed, 0 errors' <<<"$output"; then
    pass "$label"
  else
    fail "$label"
  fi
}

clangd_check "$FC_DIR/src/Mod/Part/App/FeatureFillet.cpp" \
  "$FC_DIR/build/debug" 'clangd parses FreeCAD with its CDB'
clangd_check "$OCC_DIR/src/ChFi3d/ChFi3d_Builder.cxx" \
  "$OCC_BUILD_DIR" 'clangd parses OCCT with its CDB'

if [ "${1:-}" = '--runtime' ]; then
  echo '== Runtime library resolution =='
  runtime_output=$(
    cd "$FC_DIR" \
      && DYLD_PRINT_LIBRARIES=1 build/debug/bin/FreeCADCmd -c \
        'import Part; b=Part.makeBox(10,10,10); b.makeFillet(2.0,[b.Edges[0]])' \
        2>&1
  )
  if grep -Fq "$LOCAL_OCC_LIB/libTKFillet" <<<"$runtime_output"; then
    pass 'Runtime loads local libTKFillet'
  else
    fail 'Runtime loads local libTKFillet'
  fi
fi

printf '== Summary: %d error(s), %d warning(s) ==\n' "$errors" "$warnings"
if [ "$errors" -ne 0 ]; then
  exit 1
fi
