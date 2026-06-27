# =====================================================================
# demo-fillet-capture — minimal FreeCAD script: fillet one box edge, then push
# the NEW fillet TOPOLOGICAL face(s) and their adjacent faces into the Print
# session, so they show up live in the 5777 viewer for everyone watching.
#
# These are real TopoDS_Faces from the FINISHED fillet (post-Build), so no
# surface->face conversion is needed — exportBrep writes them directly, the
# occ-mesh-daemon meshes each, and the viewer renders them (fillet = orange,
# neighbours = teal).
#
#   Run:  scripts/fc-cmd.sh scripts/demo-fillet-capture.py
#   Watch: http://127.0.0.1:5777/   (start the daemon first:
#          scripts/occ-debug-start.sh start)
# =====================================================================
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import occ_capture as cap  # reuse the flock event-append + run/seq helpers

import Part  # FreeCAD

SESSION = REPO / ".occ-debug" / "sessions" / "dev"
os.environ["OCC_DEBUG_SESSION"] = str(SESSION)
(SESSION / "assets").mkdir(parents=True, exist_ok=True)

FILLET_COLOR = "#e0a34e"    # orange — the new fillet faces
NEIGHBOUR_COLOR = "#78b6a3"  # teal — adjacent planar faces
SEAM_COLOR = "#ff5d5d"       # red — shared edges (fillet ↔ neighbour seams)


def emit_face(face, ent_id, group, label, color):
    """Write a single TopoDS_Face to BREP in the session + append a shape add
    (real bbox placeholder; the daemon swaps in the meshed surface)."""
    run_id = cap._run_id(SESSION)
    rel = f"{run_id}/{ent_id.replace('/', '_')}.brep"
    abspath = SESSION / "assets" / rel
    abspath.parent.mkdir(parents=True, exist_ok=True)
    face.exportBrep(str(abspath))
    bb = face.BoundBox
    cap._append(
        SESSION,
        op="add",
        id=ent_id,
        group=group,
        kind="shape",
        label=label,
        geometry={"bbox": {"min": [bb.XMin, bb.YMin, bb.ZMin], "max": [bb.XMax, bb.YMax, bb.ZMax]}},
        asset={"format": "occt-brep", "path": rel},
        style={"color": color, "opacity": 0.6},
        metadata={"producer": "demo-fillet", "surface": type(face.Surface).__name__},
    )


def surface_name(face):
    return type(face.Surface).__name__


def discretize(edge, n=24):
    return [[p.x, p.y, p.z] for p in edge.discretize(Number=n)]


def run():
    # --- build a box and fillet ALL FOUR vertical edges -----------------------
    box = Part.makeBox(10, 20, 30)
    vertical = [
        e for e in box.Edges
        if abs(e.Vertexes[0].Z - e.Vertexes[1].Z) > 1e-6
        and abs(e.Vertexes[0].X - e.Vertexes[1].X) < 1e-6
        and abs(e.Vertexes[0].Y - e.Vertexes[1].Y) < 1e-6
    ]
    fillet = box.makeFillet(2.0, vertical)

    # new fillet faces = any non-planar face of the result (box faces are planes)
    fillet_faces = [f for f in fillet.Faces if surface_name(f) != "Plane"]

    # for each fillet face: its planar neighbours + the edges it SHARES with them
    neighbours, seams = [], []
    for ff in fillet_faces:
        for e in ff.Edges:
            if not any(e.isSame(x) for x in seams):
                seams.append(e)  # a fillet-face boundary edge == a shared seam
            for nf in fillet.ancestorsOfType(e, Part.Face):
                if surface_name(nf) == "Plane" and not any(nf.isSame(x) for x in neighbours):
                    neighbours.append(nf)

    # --- emit into the live Print session -------------------------------------
    # Stable ids are fine: the daemon keys idempotency on the brep PATH, so a
    # re-run (new brep under a new run) re-meshes even though the ids repeat.
    cap._append(SESSION, op="clear_scene", include_protected=True, metadata={"reason": "fillet-demo"})
    for i, ff in enumerate(fillet_faces):
        emit_face(ff, f"fillet/face-{i}", "fillet/faces", f"圆角面 {i} · {surface_name(ff)}", FILLET_COLOR)
    for i, nf in enumerate(neighbours):
        emit_face(nf, f"fillet/neighbour-{i}", "fillet/neighbours", f"邻面 {i} · {surface_name(nf)}", NEIGHBOUR_COLOR)
    for i, e in enumerate(seams):  # shared edges as bright xray polylines, on top
        cap._append(
            SESSION, op="add", id=f"fillet/seam-{i}", group="fillet/seams", kind="edge",
            label=f"共享边 {i}", geometry={"points": discretize(e)},
            style={"color": SEAM_COLOR, "line_width": 4, "depth_mode": "xray"},
            metadata={"producer": "demo-fillet"},
        )
    if fillet_faces:
        cap._append(SESSION, op="focus", id="fillet/face-0")

    # --- console summary (the "print it out" part) ----------------------------
    print(f"[fillet-demo] {len(vertical)} edges filleted -> {len(fillet_faces)} fillet face(s), "
          f"{len(neighbours)} neighbour(s), {len(seams)} shared edge(s)")
    for i, ff in enumerate(fillet_faces):
        print(f"  圆角面 {i}: surface={surface_name(ff)}  area={ff.Area:.2f}  edges={len(ff.Edges)}")
    print(f"[fillet-demo] live at http://127.0.0.1:5777/")


# FreeCADCmd can source a script more than once; run the body exactly once.
if not globals().get("_FILLET_DEMO_DONE"):
    _FILLET_DEMO_DONE = True
    run()
