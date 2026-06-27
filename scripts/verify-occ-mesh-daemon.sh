#!/usr/bin/env bash
# =====================================================================
# Offline acceptance test for occ-mesh-daemon S1+S3 (occ-mesh-daemon-plan.md §6).
#
# Fully offline — no LLDB, no FreeCAD, no live OCCT session. The mesher
# self-locates OCCT via baked rpath. Exercises the whole daemon loop:
#
#   1. build the mesher (idempotent; rpath-resolved)
#   2. --make-test-nonmanifold -> a REAL brep at assets/run-0001/shape-7.brep
#   3. fake-occ-session --emit-shape-asset run-0001/shape-7.brep
#        -> a placeholder shape+occt-brep `add` (id=shape-7)
#   4. occ-mesh-daemon.py --session DIR --once
#        -> meshes the brep, appends a run-0001/mesh `update` + a `defect`
#   5. assert (happy path):
#        - update(run-0001/mesh, id=shape-7, patch.asset.format=print-mesh)
#        - that update's asset.sha256 == sha256(the produced mesh.json)
#        - the placeholder add is preserved (daemon never truncates)
#        - a `defect` event with ref.entity_id==shape-7 (S3 / §4)
#        - the mesh-run seq is monotonic + unique
#        - a second --once adds NO new lines (idempotency, §8)
#        - EVERY event line validates against event.schema.json (jsonschema)
#   6. assert (N6 failure path, separate session): a corrupt brep yields a
#        `note(level:"capture_failure")` and NO update (plan §5 N6).
#
#   Usage: scripts/verify-occ-mesh-daemon.sh
# =====================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$HERE/.." && pwd)"
BIN="${OCC_DEBUG_MESH_BIN:-$WS/tools/occ-debug-mesh/build/occ-debug-mesh}"
SCHEMA="$WS/tools/Print/protocol/event.schema.json"

if [ ! -x "$BIN" ]; then
  echo "[verify-daemon] mesher missing, building -> $BIN"
  "$HERE/build-occ-debug-mesh.sh"
fi

SESS="$(mktemp -d)"
FAIL_SESS="$(mktemp -d)"
trap 'rm -rf "$SESS" "$FAIL_SESS"' EXIT

# ---- happy path -----------------------------------------------------------
BREP_REL="run-0001/shape-7.brep"
mkdir -p "$SESS/assets/run-0001"
echo "[verify-daemon] happy-path session=$SESS"

# 1+2. real non-manifold brep dropped straight into assets/run-0001/
"$BIN" --make-test-nonmanifold "$SESS/assets/$BREP_REL" >/dev/null 2>&1

# 3. placeholder add (shape + occt-brep asset) referencing it
python3 "$HERE/fake-occ-session.py" --session "$SESS" --emit-shape-asset "$BREP_REL"

# 4. run the daemon once: mesh + append update + defect
OCC_DEBUG_MESH_BIN="$BIN" python3 "$HERE/occ-mesh-daemon.py" --session "$SESS" --once

# idempotency: a second --once must not append anything
N1="$(grep -c . "$SESS/events.ndjson")"
OCC_DEBUG_MESH_BIN="$BIN" python3 "$HERE/occ-mesh-daemon.py" --session "$SESS" --once >/dev/null
N2="$(grep -c . "$SESS/events.ndjson")"

# restart (V1): a FRESH daemon process meshing a NEW brep in the SAME run must
# continue the mesh-run seq (reconstructed from the log), not reset to 1.
"$BIN" --make-test-nonmanifold "$SESS/assets/run-0001/shape-8.brep" >/dev/null 2>&1
python3 "$HERE/fake-occ-session.py" --session "$SESS" --emit-shape-asset run-0001/shape-8.brep >/dev/null
OCC_DEBUG_MESH_BIN="$BIN" python3 "$HERE/occ-mesh-daemon.py" --session "$SESS" --once >/dev/null

# crash recovery: a mesh.json already on disk with NO update in the log (daemon
# died between meshing and appending) must be emitted from, without re-meshing.
"$BIN" --make-test-nonmanifold "$SESS/assets/run-0001/shape-9.brep" >/dev/null 2>&1
"$BIN" "$SESS/assets/run-0001/shape-9.brep" "$SESS/assets/run-0001/shape-9.mesh.json" >/dev/null 2>&1
python3 "$HERE/fake-occ-session.py" --session "$SESS" --emit-shape-asset run-0001/shape-9.brep >/dev/null
OCC_DEBUG_MESH_BIN="$BIN" python3 "$HERE/occ-mesh-daemon.py" --session "$SESS" --once >/dev/null

# ---- N6 failure path ------------------------------------------------------
echo "[verify-daemon] failure-path session=$FAIL_SESS"
mkdir -p "$FAIL_SESS/assets/run-0001"
printf 'not a real brep' > "$FAIL_SESS/assets/run-0001/bad-1.brep"
python3 "$HERE/fake-occ-session.py" --session "$FAIL_SESS" --emit-shape-asset run-0001/bad-1.brep >/dev/null
OCC_DEBUG_MESH_BIN="$BIN" python3 "$HERE/occ-mesh-daemon.py" --session "$FAIL_SESS" --once 2>/dev/null

# ---- assertions -----------------------------------------------------------
OCC_DM_SESS="$SESS" OCC_DM_FAIL="$FAIL_SESS" OCC_DM_SCHEMA="$SCHEMA" \
OCC_DM_N1="$N1" OCC_DM_N2="$N2" python3 - <<'PY'
import hashlib, json, os, sys

sess = os.environ["OCC_DM_SESS"]
fail_sess = os.environ["OCC_DM_FAIL"]
schema_path = os.environ["OCC_DM_SCHEMA"]
n1, n2 = int(os.environ["OCC_DM_N1"]), int(os.environ["OCC_DM_N2"])

fails = 0
def check(desc, ok, detail=""):
    global fails
    tag = "PASS" if ok else "FAIL"
    if not ok:
        fails += 1
    print(f"[{tag}] {desc}" + (f"  ({detail})" if detail and not ok else ""))

def load(path):
    out = []
    with open(path, encoding="utf-8") as fp:
        for ln, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError as e:
                check(f"{path} line {ln} is valid JSON", False, str(e))
    return out

events = load(os.path.join(sess, "events.ndjson"))
evf = load(os.path.join(fail_sess, "events.ndjson"))
check("events.ndjson has lines", len(events) > 0, f"{len(events)} events")

# --- the daemon's update ---
updates = [e for e in events if e.get("op") == "update"
           and e.get("run_id") == "run-0001/mesh" and e.get("id") == "shape-7"]
check("update(run-0001/mesh, id=shape-7) present", len(updates) == 1, f"found {len(updates)}")
if updates:
    asset = updates[0].get("patch", {}).get("asset", {})
    check("update.patch.asset.format == print-mesh",
          asset.get("format") == "print-mesh", repr(asset.get("format")))
    mesh_rel = asset.get("path")
    check("update.patch.asset.path set", bool(mesh_rel), repr(mesh_rel))
    if mesh_rel:
        mesh_abs = os.path.join(sess, "assets", mesh_rel)
        check("produced mesh.json exists", os.path.exists(mesh_abs), mesh_abs)
        if os.path.exists(mesh_abs):
            h = hashlib.sha256()
            with open(mesh_abs, "rb") as mp:
                for chunk in iter(lambda: mp.read(1 << 16), b""):
                    h.update(chunk)
            want, got = h.hexdigest(), asset.get("sha256")
            check("asset.sha256 == sha256(mesh.json)", got == want, f"got={got} want={want}")

# --- the placeholder add is preserved (daemon never truncates) ---
adds = [e for e in events if e.get("op") == "add" and e.get("id") == "shape-7"]
check("placeholder add(shape-7) preserved", len(adds) == 1, f"found {len(adds)}")

# --- S3: defect events emitted, ref.entity_id stamped ---
defects = [e for e in events if e.get("kind") == "defect"]
check("defect event emitted (S3)", len(defects) >= 1, f"found {len(defects)}")
if defects:
    ref = defects[0].get("defect", {}).get("ref", {})
    check("defect.ref.entity_id == shape-7", ref.get("entity_id") == "shape-7", repr(ref))
    check("defect run_id == run-0001/mesh",
          defects[0].get("run_id") == "run-0001/mesh", repr(defects[0].get("run_id")))

# --- the mesh-run seq is monotonic + unique ---
seqs = [e["seq"] for e in events if e.get("run_id") == "run-0001/mesh"]
check("mesh-run seq monotonic + unique", seqs == sorted(seqs) and len(seqs) == len(set(seqs)), repr(seqs))

# --- idempotency: second --once added nothing ---
check("second --once is a no-op (idempotent)", n1 == n2, f"{n1} -> {n2}")

# --- restart (V1): seq reconstructed, not reset; shape-7 not re-emitted ---
check("shape-7 update emitted exactly once across restarts",
      len([e for e in events if e.get("op") == "update" and e.get("id") == "shape-7"]) == 1)
check("restart continues the mesh-run seq (shape-8 update present)",
      len([e for e in events if e.get("op") == "update" and e.get("id") == "shape-8"]) == 1)

# --- crash recovery: shape-9 emitted from a pre-existing mesh.json ---
u9 = [e for e in events if e.get("op") == "update" and e.get("id") == "shape-9"]
check("shape-9 recovered from existing mesh (no re-mesh)", len(u9) == 1, f"found {len(u9)}")
if u9:
    a9 = u9[0].get("patch", {}).get("asset", {})
    m9 = os.path.join(sess, "assets", a9.get("path", ""))
    if os.path.exists(m9):
        h9 = hashlib.sha256(open(m9, "rb").read()).hexdigest()
        check("shape-9 recovered asset.sha256 matches mesh bytes", a9.get("sha256") == h9)

# --- N6 failure path: capture_failure note, NO update ---
notes = [e for e in evf if e.get("op") == "note" and e.get("level") == "capture_failure"]
check("failure -> capture_failure note", len(notes) >= 1, f"found {len(notes)}")
check("failure -> NO update", not [e for e in evf if e.get("op") == "update"], "update present")

# --- every line (both sessions) validates against event.schema.json ---
try:
    import jsonschema
    with open(schema_path, encoding="utf-8") as sp:
        schema = json.load(sp)
    validator = jsonschema.Draft202012Validator(schema)
    bad = []
    for tag, evs in (("ok", events), ("fail", evf)):
        for i, e in enumerate(evs):
            errs = sorted(validator.iter_errors(e), key=lambda x: list(x.path))
            if errs:
                bad.append((tag, i, e.get("op"), errs[0].message))
    check("all event lines pass event.schema.json", not bad,
          "; ".join(f"{t}#{i}({op}): {msg}" for t, i, op, msg in bad[:4]))
except ImportError:
    check("jsonschema importable", False, "pip install jsonschema")

print()
if fails:
    print(f"[verify-daemon] {fails} assertion(s) FAILED")
    sys.exit(1)
print("[verify-daemon] all assertions passed (S1 + S3)")
PY
