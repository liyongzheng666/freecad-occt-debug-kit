#!/usr/bin/env bash
# =====================================================================
# One-click bootstrap: materialize a buildable + debuggable FreeCAD/OCCT
# environment from a fresh clone of this configuration kit.
#
# This kit ignores the FreeCAD/, occt/, and tools/Print/ source trees, so a
# clone only carries config, scripts, docs, templates, and patches. This
# script pins and clones the matching sources, re-applies the local edits that
# live inside those ignored trees, builds both, and verifies the result.
#
# Idempotent: re-running skips any step already completed, so it also
# doubles as a repair entry point.
#
#   Usage: scripts/bootstrap.sh [JOBS]      # JOBS defaults to 8
# =====================================================================
set -euo pipefail

# ---- Pinned sources (the exact revisions this kit was captured against) ----
OCCT_URL="https://github.com/Open-Cascade-SAS/OCCT.git"
OCCT_REF="V7_8_1"
FREECAD_URL="https://github.com/FreeCAD/FreeCAD.git"
FREECAD_SHA="2b7e9a6896bc9b5dc4555c2f6faa9adc0a7caf47"   # ancestor of FreeCAD/main
PRINT_URL="https://github.com/liyongzheng666/Print.git"
PRINT_SHA="b69d0d19f9c756f756cf7805795b7f3c8c5e7180"     # pinned Print viewer/bridge revision

JOBS="${1:-8}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$WS"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }

# ---- Prerequisites --------------------------------------------------------
step "Check prerequisites"
missing=0
for tool in git pixi; do
  if command -v "$tool" >/dev/null 2>&1; then
    note "found $tool"
  else
    echo "[!] missing prerequisite: $tool" >&2
    missing=1
  fi
done
[ "$missing" -eq 0 ] || { echo "[!] install the missing tools and re-run." >&2; exit 1; }

# ---- 1. OCCT source @ V7_8_1 + local debug/build patch --------------------
if [ ! -d occt/.git ]; then
  step "Clone OCCT $OCCT_REF"
  git clone --depth 1 --branch "$OCCT_REF" "$OCCT_URL" occt
else
  step "OCCT already present — skip clone ($(git -C occt describe --tags --always))"
fi

if git -C occt apply --reverse --check "$WS/patches/occt-debug-build.patch" >/dev/null 2>&1; then
  note "OCCT debug/build patch already applied — skip"
else
  step "Apply OCCT debug/build patch (keep debug map for LLDB + Clang 18 cast fix)"
  git -C occt apply "$WS/patches/occt-debug-build.patch"
fi

# ---- 2. FreeCAD source pinned to the exact captured commit ----------------
if [ ! -d FreeCAD/.git ]; then
  step "Clone FreeCAD (partial) and pin to $FREECAD_SHA"
  git clone --filter=blob:none "$FREECAD_URL" FreeCAD
  git -C FreeCAD checkout "$FREECAD_SHA"
else
  step "FreeCAD already present — skip clone (current: $(git -C FreeCAD rev-parse --short HEAD))"
fi

# ---- 2b. Print viewer/bridge pinned to the captured commit ----------------
if [ ! -d tools/Print/.git ]; then
  step "Clone Print (partial) and pin to $PRINT_SHA"
  git clone --filter=blob:none "$PRINT_URL" tools/Print
  git -C tools/Print checkout "$PRINT_SHA"
else
  step "Print already present — skip clone (current: $(git -C tools/Print rev-parse --short HEAD))"
fi

# ---- 3. Restore files that live inside the ignored FreeCAD tree -----------
step "Restore FreeCAD overlay files (local CMake preset + toponaming note)"
cp "$WS/templates/CMakeUserPresets.json" FreeCAD/CMakeUserPresets.json
note "FreeCAD/CMakeUserPresets.json"
if [ -f "$WS/templates/TOPONAMING.md" ]; then
  mkdir -p FreeCAD/src/Mod/Part/App
  cp "$WS/templates/TOPONAMING.md" FreeCAD/src/Mod/Part/App/TOPONAMING.md
  note "FreeCAD/src/Mod/Part/App/TOPONAMING.md"
fi

# ---- 4. Materialize the locked Pixi toolchain -----------------------------
step "Materialize locked Pixi toolchain (Clang 18, CMake, Ninja, Qt, ...)"
( cd FreeCAD && pixi install --frozen )

# ---- 5. Build OCCT (debug) and install ------------------------------------
step "Configure + build OCCT (debug) and install to occt/install/debug"
"$SCRIPT_DIR/configure-occt.sh"
"$SCRIPT_DIR/rebuild-occ.sh" "$JOBS"

# ---- 6. Build FreeCAD against the local OCCT ------------------------------
step "Configure + build FreeCAD against local OCCT (-j$JOBS)"
( cd FreeCAD
  pixi run --frozen -- cmake --preset local-occt-macos-debug
  pixi run --frozen -- cmake --build build/debug -j "$JOBS" )

# ---- 7. Verify ------------------------------------------------------------
step "Verify toolchain, indexing, and runtime library resolution"
"$SCRIPT_DIR/workspace-doctor.sh" --runtime

step "Bootstrap complete."
note "Open the workspace with:  code ."
note "Run the smoke scenario:  scripts/fc-cmd.sh scripts/debug_target.py"
