#!/usr/bin/env python3
"""Turn occ-debug-mesh output (print-mesh JSON) into a Print Bridge session.

The Print viewer (the M1 interactive Three.js UI) renders inline `edge`/
`polyline` entities streamed from the Bridge's /events SSE. The asset->mesh
render path isn't built yet (M2-3), and the viewer has no triangle-mesh
renderer — but discretized EDGES are exactly what M1 shows ("点和离散边"), so
this emits each `edges[]` polyline as an `edge` entity plus a bbox baseline for
spatial reference. Result: my §7 edges, draggable/zoomable in the real viewer.

    scripts/mesh-to-session.py box.mesh.json [more.mesh.json ...] \
        --session .occ-debug/sessions/dev
    # then: bridge/bridge.py --session DIR --port 7341  +  npm run dev
"""
import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = "1.0"
EDGE_COLORS = [
    "#ff7f0e", "#1f9bff", "#2ecc71", "#e74c3c", "#b07cff", "#1abc9c",
    "#f1c40f", "#ff5da2", "#7fd13b", "#ff9f40", "#36d1c4", "#ff6b6b",
]
# Muted, translucent surface tones so faces read as a solid and the bright
# edges still pop on top.
FACE_COLORS = [
    "#6f7d9b", "#8a7d9b", "#6f9b8a", "#9b8a6f", "#7d9b6f", "#9b6f7d",
]


def triples(flat):
    return [[flat[i], flat[i + 1], flat[i + 2]] for i in range(0, len(flat), 3)]


def uvpairs(flat):
    return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="*.mesh.json from occ-debug-mesh")
    ap.add_argument("--session", default=os.environ.get("OCC_DEBUG_SESSION", ".occ-debug/sessions/dev"))
    ap.add_argument("--session-id", default="occ-mesh-demo")
    ap.add_argument("--no-faces", action="store_true", help="edges only (skip face surfaces)")
    ap.add_argument("--no-edges", action="store_true", help="faces only (skip edge polylines)")
    ap.add_argument("--fresh", action="store_true", help="truncate the session (start a new run-0001)")
    args = ap.parse_args(argv)

    os.makedirs(os.path.join(args.session, "assets"), exist_ok=True)
    out = os.path.join(args.session, "events.ndjson")
    # Reset semantics (linkage doc §8): a re-run does NOT truncate — that breaks
    # connected viewers' tail offset. Instead APPEND a clear_scene + the new
    # objects under a NEW run_id, so live viewers swap without a reload.
    prev_runs = []
    if os.path.exists(out) and not args.fresh:
        with open(out) as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = re.match(r"run-(\d+)$", json.loads(line).get("run_id", ""))
                except ValueError:
                    continue
                if m:
                    prev_runs.append(int(m.group(1)))
    is_reset = bool(prev_runs)
    run_id = f"run-{(max(prev_runs) + 1) if prev_runs else 1:04d}"
    events = []
    seq = 0
    env = {"schema_version": SCHEMA_VERSION, "session_id": args.session_id, "run_id": run_id}

    def emit(**ev):
        nonlocal seq
        seq += 1
        events.append({**env, "seq": seq, **ev})

    if is_reset:
        emit(op="clear_scene", include_protected=True)  # wipe the previous run's objects (live swap)

    # P0c: a NURBS control net -> point_set (poles) + polyline grid lines, in a
    # per-owner subgroup, hidden by default (toggle on in the layer tree).
    def emit_control_net(base, owner_id, ctrl):
        grp = f"occ-debug-mesh/{base}/control-net/{owner_id}"
        pts = triples(ctrl["poles"])
        nb_u, nb_v = ctrl["nb_u"], ctrl["nb_v"]
        emit(op="add", id=f"{grp}/poles", group=grp, kind="point_set",
             label=f"{owner_id} 控制点×{len(pts)}",
             geometry={"positions": pts}, style={"color": "#f1c40f", "size": 6})
        if nb_v == 0:  # curve: one control polygon through the poles
            emit(op="add", id=f"{grp}/poly", group=grp, kind="polyline",
                 label=f"{owner_id} 控制多边形",
                 geometry={"points": pts}, style={"color": "#f1c40f", "line_width": 1})
        else:          # surface: grid lines (row-major, u outer / v inner)
            for i in range(nb_u):
                emit(op="add", id=f"{grp}/u{i}", group=grp, kind="polyline", label=f"{owner_id} u{i}",
                     geometry={"points": [pts[i * nb_v + j] for j in range(nb_v)]},
                     style={"color": "#caa83a", "line_width": 1})
            for j in range(nb_v):
                emit(op="add", id=f"{grp}/v{j}", group=grp, kind="polyline", label=f"{owner_id} v{j}",
                     geometry={"points": [pts[i * nb_v + j] for i in range(nb_u)]},
                     style={"color": "#caa83a", "line_width": 1})
        emit(op="set_visibility", target={"type": "group", "id": grp}, visible=False)

    color_i = 0
    first_bbox_id = None
    for path in args.files:
        with open(path) as fp:
            mesh = json.load(fp)
        base = os.path.basename(path).replace(".mesh.json", "")
        faces = [] if args.no_faces else mesh.get("faces", [])
        edges = [] if args.no_edges else mesh.get("edges", [])
        # P0b: pull the geom sidecar (types/tolerance/UV pcurves) to enrich metadata.
        geom_path = path.replace(".mesh.json", ".geom.json")
        geom = json.load(open(geom_path)) if os.path.exists(geom_path) else {}
        fg = {f["id"]: f for f in geom.get("faces", [])}
        eg = {e["id"]: e for e in geom.get("edges", [])}
        pc_by_face = {}  # face_id -> its full parameter-space boundary (all pcurves on it)
        for ge in geom.get("edges", []):
            for pc in ge.get("pcurves", []):
                pc_by_face.setdefault(pc["face_id"], []).append(
                    {"label": ge["id"], "is_seam": pc["is_seam"],
                     "degenerate": ge["degenerate"], "points": uvpairs(pc["uv"])})
        all_pts = [p for e in edges for p in triples(e["points"])]
        all_pts += [p for f in faces for p in triples(f["positions"])]
        if not all_pts:
            print(f"warning: {path}: nothing to show", file=sys.stderr)
            continue

        # bbox baseline (protected, persists across reset runs) for spatial frame.
        xs = [p[0] for p in all_pts]; ys = [p[1] for p in all_pts]; zs = [p[2] for p in all_pts]
        bbox_id = f"baseline/{base}/bounds"
        if first_bbox_id is None:
            first_bbox_id = bbox_id
        emit(op="add", id=bbox_id, group=f"baseline/{base}", kind="bbox",
             label=f"{base} 包围盒",
             geometry={"min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
             style={"color": "#858d82", "opacity": 0.5, "protected": True})

        # each face -> a shaded translucent `face` entity (triangle mesh).
        for fi, f in enumerate(faces):
            fid = f["face_id"]
            geom = {"positions": f["positions"], "indices": f["indices"]}
            if f.get("normals"):
                geom["normals"] = f["normals"]
            md = {"source": "occ-debug-mesh", "fixture": base}
            gf = fg.get(fid)
            if gf:
                md["surface_type"] = gf["surface_type"]
                md["tolerance"] = gf["tolerance"]
                md["uv_bounds"] = gf["uv_bounds"]
                per = ("U" if gf["periodic_u"] else "") + ("V" if gf["periodic_v"] else "")
                if per:
                    md["periodic"] = per
                # one panel = this face's full parameter-space unwrap.
                md["uv"] = {"panels": [{"face_id": fid, "surface_type": gf["surface_type"],
                                        "bounds": gf["uv_bounds"], "curves": pc_by_face.get(fid, [])}]}
                if gf.get("control"):
                    c = gf["control"]
                    md["control"] = f"bspline deg({c['degree_u']},{c['degree_v']}) {c['nb_u']}×{c['nb_v']}, poles {len(c['poles'])//3}"
            emit(op="add", id=f"occ-debug-mesh/{base}/{fid}", group=f"occ-debug-mesh/{base}/faces",
                 kind="face", label=f"{base} {fid}",
                 geometry=geom,
                 style={"color": FACE_COLORS[fi % len(FACE_COLORS)], "opacity": 0.5},
                 topology_ref={"freecad_element": fid, "shape_type": "FACE",
                               "orientation": f.get("orientation", "FORWARD")},
                 metadata=md)
            if gf and gf.get("control"):
                emit_control_net(base, fid, gf["control"])

        # each discretized edge -> an interactive `edge` entity (the §7 payload).
        for e in edges:
            eid = e["edge_id"]
            md = {"source": "occ-debug-mesh", "fixture": base}
            ge = eg.get(eid)
            if ge:
                md["curve_type"] = ge["curve_type"]
                md["tolerance"] = ge["tolerance"]
                if ge["degenerate"]:
                    md["degenerate"] = True
                if ge["closed"]:
                    md["closed"] = True
                # An edge can lie on several faces, each a DIFFERENT parameter
                # space (e.g. a closed circle on a cylinder vs its planar cap).
                # Never mix them in one plot: one panel per face, with this
                # edge highlighted inside that face's full unwrap.
                touched = []
                for pc in ge.get("pcurves", []):
                    if pc["face_id"] not in touched:
                        touched.append(pc["face_id"])
                panels = []
                for fcid in touched:
                    gfc = fg.get(fcid)
                    curves = [{**c, "selected": c["label"] == eid} for c in pc_by_face.get(fcid, [])]
                    panels.append({"face_id": fcid,
                                   "surface_type": gfc["surface_type"] if gfc else "",
                                   "bounds": gfc["uv_bounds"] if gfc else None,
                                   "curves": curves})
                if panels:
                    md["uv"] = {"panels": panels}
                if ge.get("control"):
                    c = ge["control"]
                    md["control"] = f"bspline deg {c['degree_u']}, poles {c['nb_u']}"
            emit(op="add", id=f"occ-debug-mesh/{base}/{eid}", group=f"occ-debug-mesh/{base}/edges",
                 kind="edge", label=f"{base} {eid}",
                 geometry={"points": triples(e["points"])},
                 style={"color": EDGE_COLORS[color_i % len(EDGE_COLORS)], "line_width": 4},
                 topology_ref={"freecad_element": eid, "shape_type": "EDGE"},
                 metadata=md)
            if ge and ge.get("control"):
                emit_control_net(base, eid, ge["control"])
            color_i += 1
        print(f"  {base}: {len(faces)} faces + {len(edges)} edges -> events", file=sys.stderr)

    emit(op="note", level="info",
         message=f"occ-debug-mesh 面+边 · {seq} events · {len(args.files)} fixture(s)")
    # Frame the geometry: the default camera is tuned for ~±5u sample data, but
    # real BREP coords can be anywhere. Focus the first bbox so the viewer fits.
    if first_bbox_id:
        emit(op="focus", id=first_bbox_id)

    with open(out, "w" if args.fresh else "a") as fp:
        for ev in events:
            fp.write(json.dumps(ev, ensure_ascii=False) + "\n")
    mode = "fresh" if args.fresh else ("reset" if is_reset else "new")
    print(f"{mode} {run_id}: {out} (+{len(events)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
