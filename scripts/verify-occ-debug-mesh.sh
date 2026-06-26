#!/usr/bin/env bash
# =====================================================================
# Offline fixture regression for occ-debug-mesh (README §6 matrix + §7 edges).
#
# Builds every --make-test-* fixture, converts it, and asserts mesh / edge /
# defect output against the locked expectations. No LLDB, no live OCCT session:
# the binary self-locates its OCCT via baked rpath, so this just runs it and
# checks the JSON. One button:
#
#   scripts/verify-occ-debug-mesh.sh         # builds the tool if missing, then verifies
# =====================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$HERE/.." && pwd)"
BIN="$WS/tools/occ-debug-mesh/build/occ-debug-mesh"

if [ ! -x "$BIN" ]; then
  echo "[verify] binary missing, building -> $BIN"
  "$HERE/build-occ-debug-mesh.sh"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Generate every fixture BREP, then convert it (mesh.json + defects.json).
for f in box located bad selfx edge nurbs bspline-edge cylinder sphere torus mirror nonmanifold; do
  "$BIN" "--make-test-$f" "$WORK/$f.brep"        >/dev/null 2>&1
  "$BIN" "$WORK/$f.brep"  "$WORK/$f.mesh.json"   >/dev/null 2>&1
done

# V2 mesh watchdog (--timeout): a tiny budget trips UserBreak before the first
# face, degrading to a partial mesh (no crash); a generous budget meshes fully.
"$BIN" --timeout 0.000001 "$WORK/box.brep" "$WORK/to-tiny.mesh.json" >/dev/null 2>&1 || true
"$BIN" --timeout 60       "$WORK/box.brep" "$WORK/to-big.mesh.json"  >/dev/null 2>&1 || true

OCC_DM_WORK="$WORK" python3 - <<'PY'
import json, os, math, sys

WORK = os.environ["OCC_DM_WORK"]
fails = 0

def load(fixture, kind):
    with open(os.path.join(WORK, f"{fixture}.{kind}.json")) as fp:
        return json.load(fp)

def check(fixture, desc, ok, detail=""):
    global fails
    tag = "PASS" if ok else "FAIL"
    if not ok:
        fails += 1
    line = f"  [{tag}] {fixture:8s} {desc}"
    if not ok and detail:
        line += f"  -> {detail}"
    print(line)

def near(a, b, tol=1e-6):
    return abs(a - b) <= tol

def pts3(flat):
    return [flat[i:i + 3] for i in range(0, len(flat), 3)]

def world_bbox(points3):
    xs = [p[0] for p in points3]; ys = [p[1] for p in points3]; zs = [p[2] for p in points3]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

def bbox_near(bb, exp, tol=1e-6):
    return all(near(a, b, tol) for a, b in zip(bb, exp))

def face_points(mesh):
    return [p for fc in mesh["faces"] for p in pts3(fc["positions"])]

def edge_points(mesh):
    return [p for e in mesh["edges"] for p in pts3(e["points"])]

def defect_pairs(defects):
    return [(d["category"], d["status"], (d.get("ref") or {}).get("face_id")) for d in defects]

def defect_edge_refs(defects):
    return [(d["category"], d["status"], (d.get("ref") or {}).get("edge_id")) for d in defects]

def winding_ok(mesh):
    # Triangle winding (right-hand rule) must agree with the stored vertex normal.
    # This is the V9 invariant: a mirror Location must flip winding AND normals
    # together, so they stay mutually consistent and outward.
    for fc in mesh["faces"]:
        ps = pts3(fc["positions"]); ns = pts3(fc.get("normals", [])); idx = fc["indices"]
        if not ns:
            continue
        for t in range(0, len(idx), 3):
            a, b, c = ps[idx[t]], ps[idx[t + 1]], ps[idx[t + 2]]
            u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            w = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            n = ns[idx[t]]
            if w[0] * n[0] + w[1] * n[1] + w[2] * n[2] <= 0:
                return False
    return True

def normals_unit(mesh):
    for fc in mesh["faces"]:
        ns = pts3(fc.get("normals", []))
        for n in ns:
            if not near(math.sqrt(n[0]**2 + n[1]**2 + n[2]**2), 1.0, 1e-6):
                return False
    return True

def normals_outward(mesh, center):
    # avg normal of each face should point away from the solid center.
    for fc in mesh["faces"]:
        ps = pts3(fc["positions"]); ns = pts3(fc["normals"])
        cx = sum(p[0] for p in ps) / len(ps)
        cy = sum(p[1] for p in ps) / len(ps)
        cz = sum(p[2] for p in ps) / len(ps)
        nx = sum(n[0] for n in ns) / len(ns)
        ny = sum(n[1] for n in ns) / len(ns)
        nz = sum(n[2] for n in ns) / len(ns)
        dot = nx*(cx-center[0]) + ny*(cy-center[1]) + nz*(cz-center[2])
        if dot <= 0:
            return False
    return True

def all_finite(points3):
    return all(math.isfinite(c) for p in points3 for c in p)

# ---- box: 6 faces / 12 tris, world bbox [0,10]x[0,20]x[0,30], 12 edges -------
m = load("box", "mesh"); d = load("box", "defects")
tris = sum(len(fc["indices"]) // 3 for fc in m["faces"])
check("box", "6 faces, 12 triangles", len(m["faces"]) == 6 and tris == 12, f"faces={len(m['faces'])} tris={tris}")
check("box", "face world bbox [0,10]x[0,20]x[0,30]",
      bbox_near(world_bbox(face_points(m)), (0, 10, 0, 20, 0, 30)), str(world_bbox(face_points(m))))
check("box", "normals unit + outward", normals_unit(m) and normals_outward(m, (5, 10, 15)))
check("box", "12 edges (§7)", len(m["edges"]) == 12, f"edges={len(m['edges'])}")
check("box", "every edge >= 2 points", all(len(e["points"]) >= 6 for e in m["edges"]))
check("box", "edge bbox == face bbox (boundary coincident)",
      bbox_near(world_bbox(edge_points(m)), (0, 10, 0, 20, 0, 30)), str(world_bbox(edge_points(m))))
check("box", "no defects", len(d) == 0, str(defect_pairs(d)))

# ---- located: rotate+translate, world bbox shifts (M2-4 lifeline, faces+edges)
m = load("located", "mesh")
exp = (80, 100, 200, 210, 300, 330)
check("located", "face world bbox X[80,100] Y[200,210] Z[300,330]",
      bbox_near(world_bbox(face_points(m)), exp), str(world_bbox(face_points(m))))
check("located", "normals unit length", normals_unit(m))
check("located", "12 edges in world coords (§7 edge world-path)",
      len(m["edges"]) == 12 and bbox_near(world_bbox(edge_points(m)), exp),
      f"edges={len(m['edges'])} bbox={world_bbox(edge_points(m))}")

# ---- bad: open shell -> NotClosed/open_boundary; edges still discretize -------
m = load("bad", "mesh"); d = load("bad", "defects")
check("bad", "5 faces (one removed)", len(m["faces"]) == 5, f"faces={len(m['faces'])}")
check("bad", "scene-level NotClosed retained",
      ("open_boundary", "BRepCheck_NotClosed", None) in defect_pairs(d), str(defect_pairs(d)))
check("bad", "4 free edges carry open_boundary edge_ref (R3)",
      len([r for (c, s, r) in defect_edge_refs(d) if c == "open_boundary" and r]) == 4,
      str([r for (c, s, r) in defect_edge_refs(d) if c == "open_boundary" and r]))
check("bad", "edges present + finite", len(m["edges"]) >= 1 and all_finite(edge_points(m)))

# ---- selfx: bowtie face fails to mesh; edges fall back to bare-curve (§7 path B)
m = load("selfx", "mesh"); d = load("selfx", "defects")
pairs = defect_pairs(d)
check("selfx", "0 meshable faces (bowtie untriangulable)", len(m["faces"]) == 0, f"faces={len(m['faces'])}")
check("selfx", "self_intersection ref=F1",
      ("self_intersection", "BRepCheck_SelfIntersectingWire", "F1") in pairs, str(pairs))
check("selfx", "UnorientableShape reported",
      any(p[1] == "BRepCheck_UnorientableShape" for p in pairs), str(pairs))
check("selfx", "4 edges via bare-curve fallback (§7)",
      len(m["edges"]) == 4 and all_finite(edge_points(m)), f"edges={len(m['edges'])}")

# ---- edge: bare edge -> exactly 1 polyline, the straight segment (§7 core) -----
m = load("edge", "mesh")
check("edge", "0 faces (graceful, no crash)", len(m["faces"]) == 0, f"faces={len(m['faces'])}")
check("edge", "exactly 1 edge polyline (was 0)", len(m["edges"]) == 1, f"edges={len(m['edges'])}")
ep = pts3(m["edges"][0]["points"]) if m["edges"] else []
ok = len(ep) == 2 and bbox_near(tuple(ep[0]), (0, 0, 0)) and bbox_near(tuple(ep[1]), (10, 5, 2))
check("edge", "E1 == (0,0,0)->(10,5,2)", ok, str(ep))

# ---- nurbs: B-spline surface -> 1 curved face + curved boundary edges (§7) -----
# NOTE: a curved edge does NOT guarantee >2 points -- a locally-straight span
# (the x=0 isoline here discretizes to 2), and a closed/seam edge has endpoints
# that coincide in 3D (distinct only in UV). So assert curve discretization at
# the fixture level (the finely-sampled boundaries), never per-edge >2.
m = load("nurbs", "mesh")
ppe = [len(e["points"]) // 3 for e in m["edges"]]
check("nurbs", "1 B-spline face", len(m["faces"]) == 1, f"faces={len(m['faces'])}")
check("nurbs", "4 boundary edges", len(m["edges"]) == 4, f"edges={len(m['edges'])}")
check("nurbs", "curved boundary densely sampled (max pts/edge >= 10)",
      (max(ppe) if ppe else 0) >= 10, f"pts/edge={ppe}")
check("nurbs", "all edge points finite", all_finite(edge_points(m)))

# ---- bspline-edge: bare B-spline curve -> 1 multi-point polyline (GCPnts) ------
m = load("bspline-edge", "mesh")
ppe = [len(e["points"]) // 3 for e in m["edges"]]
check("bspline-edge", "0 faces", len(m["faces"]) == 0, f"faces={len(m['faces'])}")
check("bspline-edge", "1 edge polyline", len(m["edges"]) == 1, f"edges={len(m['edges'])}")
check("bspline-edge", "curve densely sampled (>= 10 pts)",
      (ppe[0] if ppe else 0) >= 10, f"pts={ppe}")
check("bspline-edge", "all edge points finite", all_finite(edge_points(m)))

# ---- mirror: reflecting Location (det<0) -> winding+normals stay outward (V9) --
m = load("mirror", "mesh")
exp = (40, 50, 0, 20, 0, 30)
check("mirror", "face world bbox X[40,50] Y[0,20] Z[0,30]",
      bbox_near(world_bbox(face_points(m)), exp), str(world_bbox(face_points(m))))
check("mirror", "normals unit + OUTWARD under mirror (V9)",
      normals_unit(m) and normals_outward(m, (45, 10, 15)))
check("mirror", "triangle winding agrees with normals (V9 core)", winding_ok(m))
check("mirror", "12 edges in world bbox",
      len(m["edges"]) == 12 and bbox_near(world_bbox(edge_points(m)), exp),
      f"edges={len(m['edges'])} bbox={world_bbox(edge_points(m))}")

# ---- nonmanifold: 3 faces share one edge -> non_manifold defect (topology) -----
m = load("nonmanifold", "mesh"); d = load("nonmanifold", "defects"); g = load("nonmanifold", "geom")
check("nonmanifold", "3 meshable faces", len(m["faces"]) == 3, f"faces={len(m['faces'])}")
nm = [e["id"] for e in g["edges"] if len(e["adjacent_faces"]) == 3]
check("nonmanifold.geom", "exactly one edge adjacent to 3 faces",
      len(nm) == 1, str([(e["id"], e["adjacent_faces"]) for e in g["edges"]]))
nm_refs = [r for (c, s, r) in defect_edge_refs(d) if c == "non_manifold"]
check("nonmanifold", "non_manifold defect (source=topology) refs the shared edge",
      len(nm) == 1 and nm[0] in nm_refs
      and any(dd["source"] == "topology" for dd in d if dd["category"] == "non_manifold"),
      f"nm={nm} refs={nm_refs}")

# ---- V2 watchdog: --timeout degrades to a partial mesh gracefully (no crash) ---
mt = load("to-tiny", "mesh")
check("watchdog", "tiny --timeout -> partial=true + failed_faces (no crash)",
      mt.get("partial") is True and len(mt.get("failed_faces", [])) >= 1,
      f"partial={mt.get('partial')} failed={len(mt.get('failed_faces', []))}")
mb = load("to-big", "mesh")
check("watchdog", "generous --timeout -> full 6-face mesh (no false abort)",
      len(mb["faces"]) == 6 and mb.get("partial") is False,
      f"faces={len(mb['faces'])} partial={mb.get('partial')}")

# ---- P0a geom sidecar: types / seams / poles / periodicity / tolerances -------
def surfaces(g): return sorted({f["surface_type"] for f in g["faces"]})
def curves(g): return sorted({e["curve_type"] for e in g["edges"]})
def seam_count(g): return sum(1 for e in g["edges"] for pc in e["pcurves"] if pc["is_seam"])
def degen_count(g): return sum(1 for e in g["edges"] if e["degenerate"])
def periodic_u(g): return any(f["periodic_u"] for f in g["faces"])
def periodic_v(g): return any(f["periodic_v"] for f in g["faces"])
def tol_ok(g):
    ts = ([v["tolerance"] for v in g["vertices"]] + [e["tolerance"] for e in g["edges"]]
          + [f["tolerance"] for f in g["faces"]])
    return bool(ts) and all(math.isfinite(t) and t > 0 for t in ts)

g = load("box", "geom")
check("box.geom", "8 vertices", len(g["vertices"]) == 8, str(len(g["vertices"])))
check("box.geom", "all plane surfaces / line edges",
      surfaces(g) == ["plane"] and curves(g) == ["line"], f"{surfaces(g)}/{curves(g)}")
check("box.geom", "no seam, no degenerate", seam_count(g) == 0 and degen_count(g) == 0)
check("box.geom", "V/E/F tolerances finite>0", tol_ok(g))

g = load("cylinder", "geom")
check("cylinder.geom", "cylinder + plane surfaces", surfaces(g) == ["cylinder", "plane"], str(surfaces(g)))
check("cylinder.geom", "circle + line edges", curves(g) == ["circle", "line"], str(curves(g)))
check("cylinder.geom", "seam edge carries 2 pcurves",
      any(sum(1 for pc in e["pcurves"] if pc["is_seam"]) == 2 for e in g["edges"]))
check("cylinder.geom", "U-periodic (not V)", periodic_u(g) and not periodic_v(g))
check("cylinder.geom", "tolerances finite>0", tol_ok(g))

g = load("sphere", "geom")
check("sphere.geom", "sphere surface", surfaces(g) == ["sphere"], str(surfaces(g)))
check("sphere.geom", "2 degenerate (pole) edges", degen_count(g) == 2, str(degen_count(g)))
check("sphere.geom", "pole edges still carry a pcurve (UV boundary)",
      all(len(e["pcurves"]) >= 1 for e in g["edges"] if e["degenerate"]))
check("sphere.geom", "seam present + U-periodic", seam_count(g) >= 2 and periodic_u(g))

g = load("torus", "geom")
check("torus.geom", "torus surface", surfaces(g) == ["torus"], str(surfaces(g)))
check("torus.geom", "U and V periodic", periodic_u(g) and periodic_v(g))
check("torus.geom", "seam pcurves present", seam_count(g) >= 2, str(seam_count(g)))

# ---- P0c control net: NURBS poles for bspline curve/surface, none for analytic -
def control_of(o):
    return o.get("control")

g = load("nurbs", "geom")
fc = next((f["control"] for f in g["faces"] if f.get("control")), None)
check("nurbs.geom", "bspline surface has control net",
      fc is not None and fc["nb_u"] == 6 and fc["nb_v"] == 6, str(fc and (fc["nb_u"], fc["nb_v"])))
check("nurbs.geom", "surface poles = nb_u*nb_v*3 world coords",
      fc is not None and len(fc["poles"]) == fc["nb_u"] * fc["nb_v"] * 3, str(fc and len(fc["poles"])))
check("nurbs.geom", "all 4 boundary edges have a control polygon",
      sum(1 for e in g["edges"] if e.get("control")) == 4)

g = load("bspline-edge", "geom")
ec = next((e["control"] for e in g["edges"] if e.get("control")), None)
check("bspline-edge.geom", "bspline curve has control polygon (7 poles, deg 6)",
      ec is not None and ec["nb_u"] == 7 and ec["degree_u"] == 6 and len(ec["poles"]) == 21,
      str(ec and (ec["nb_u"], ec["degree_u"], len(ec["poles"]))))

for analytic in ["box", "cylinder"]:
    g = load(analytic, "geom")
    has = any(o.get("control") for o in g["faces"] + g["edges"])
    check(f"{analytic}.geom", "no control net (analytic)", not has)

print()
if fails:
    print(f"[verify] FAILED: {fails} check(s) failed")
    sys.exit(1)
print("[verify] all checks passed")
PY
