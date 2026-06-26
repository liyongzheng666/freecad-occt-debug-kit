#!/usr/bin/env python3
"""Browser review for the occ-debug-mesh P0a geom sidecar (<base>.geom.json).

Per fixture: a 3D isometric view (faces + edges, from the mesh) next to per-face
UV (parameter-space) plots that draw each face's uv_bounds rectangle and the
pcurves on it — seam edges paired (two pcurves, red), pole/degenerate edges
marked (orange) — plus a table of surface/curve types, tolerances, periodicity
and flags. Zero dependencies (inline SVG); opens in any browser.

This is an offline *review* of the geom data (P0a). The real 3D↔2D viewer is P0b.

    scripts/geom-view.py a.geom.json b.geom.json      # writes HTML + opens browser
    scripts/geom-view.py --no-open --out v.html /tmp/occ-mesh-demo/*.geom.json
"""
import argparse
import json
import math
import os
import sys

_COS30, _SIN30 = math.cos(math.radians(30)), math.sin(math.radians(30))
EDGE_COLORS = ["#1f9bff", "#2ecc71", "#7fd13b", "#36d1c4", "#b07cff", "#1abc9c"]


# ---- 3D isometric (faces + edges) from the render mesh ---------------------
def _iso(x, y, z):
    return ((x - y) * _COS30, (x + y) * _SIN30 - z)


def _tri(flat):
    return [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3)]


def svg_3d(mesh, target=320, pad=24):
    faces = [(_tri(f["positions"]), f["indices"]) for f in mesh.get("faces", [])]
    edges = [_tri(e["points"]) for e in mesh.get("edges", [])]
    proj = [_iso(*p) for v, _ in faces for p in v] + [_iso(*p) for e in edges for p in e]
    if not proj:
        return '<div class="empty">（无 3D 网格）</div>'
    xs = [a for a, _ in proj]; ys = [b for _, b in proj]
    minx, miny = min(xs), min(ys)
    span = max(max(xs) - minx, max(ys) - miny, 1e-9)
    s = target / span
    W, H = (max(xs) - minx) * s + 2 * pad, (max(ys) - miny) * s + 2 * pad

    def T(p):
        sx, sy = _iso(*p)
        return ((sx - minx) * s + pad, (sy - miny) * s + pad)

    out = [f'<svg width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">',
           f'<rect width="100%" height="100%" fill="#0f1115"/>']
    for verts, idx in faces:
        for t in range(0, len(idx), 3):
            pts = " ".join(f"{X:.1f},{Y:.1f}" for X, Y in (T(verts[v]) for v in idx[t:t + 3]))
            out.append(f'<polygon points="{pts}" fill="#5a6b8c" fill-opacity="0.12" stroke="#5a6b8c" stroke-width="0.4"/>')
    for n, e in enumerate(edges):
        d = "M" + " L".join(f"{X:.1f},{Y:.1f}" for X, Y in (T(p) for p in e))
        out.append(f'<path d="{d}" fill="none" stroke="{EDGE_COLORS[n % len(EDGE_COLORS)]}" stroke-width="2"/>')
    out.append("</svg>")
    return "\n".join(out)


# ---- UV (parameter space) per face -----------------------------------------
def uv_pts(flat):
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]


def svg_uv(face, pcurves, target=240, pad=30):
    """pcurves: list of (edge_id, is_seam, degenerate, uv_flat) on this face."""
    umin, umax, vmin, vmax = face["uv_bounds"]
    all_uv = [p for _, _, _, uv in pcurves for p in uv_pts(uv)]
    us = [umin, umax] + [p[0] for p in all_uv]
    vs = [vmin, vmax] + [p[1] for p in all_uv]
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    spanu, spanv = max(u1 - u0, 1e-9), max(v1 - v0, 1e-9)
    s = target / max(spanu, spanv)
    W, H = spanu * s + 2 * pad, spanv * s + 2 * pad

    def T(u, v):
        return ((u - u0) * s + pad, H - pad - (v - v0) * s)  # V up

    out = [f'<svg width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">',
           f'<rect width="100%" height="100%" fill="#12151b"/>']
    # uv_bounds rectangle
    bx0, by0 = T(umin, vmax); bx1, by1 = T(umax, vmin)
    out.append(f'<rect x="{bx0:.1f}" y="{by0:.1f}" width="{bx1-bx0:.1f}" height="{by1-by0:.1f}" '
               f'fill="none" stroke="#3b4150" stroke-width="1" stroke-dasharray="3 3"/>')
    # pcurves
    for eid, is_seam, degen, uv in pcurves:
        pts = [T(u, v) for u, v in uv_pts(uv)]
        if not pts:
            continue
        color = "#e74c3c" if is_seam else ("#ff9f40" if degen else "#36d1c4")
        width = 3 if is_seam else 2.2
        if len(pts) == 1:
            X, Y = pts[0]
            out.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="3" fill="{color}"/>')
        else:
            d = "M" + " L".join(f"{X:.1f},{Y:.1f}" for X, Y in pts)
            dash = ' stroke-dasharray="5 3"' if degen else ""
            out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash}/>')
        for X, Y in pts:
            out.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="1.8" fill="{color}"/>')
    out.append(f'<text x="6" y="{H-6:.0f}" fill="#7a8290" font-size="10">U →</text>')
    out.append(f'<text x="6" y="14" fill="#7a8290" font-size="10">V ↑</text>')
    out.append("</svg>")
    return "\n".join(out)


def face_badges(f):
    b = []
    if f.get("periodic_u"): b.append("U周期")
    if f.get("periodic_v"): b.append("V周期")
    if f.get("closed_u") and not f.get("periodic_u"): b.append("U闭合")
    return " ".join(f'<span class="badge">{x}</span>' for x in b)


def tables(geom):
    edges_by_face = {}
    edge_meta = {e["id"]: e for e in geom.get("edges", [])}
    for e in geom.get("edges", []):
        for pc in e.get("pcurves", []):
            edges_by_face.setdefault(pc["face_id"], []).append(
                (e["id"], pc["is_seam"], e["degenerate"], pc["uv"]))

    uvs = []
    for f in geom.get("faces", []):
        pcs = edges_by_face.get(f["id"], [])
        ub = ",".join(f"{x:.3g}" for x in f["uv_bounds"])
        uvs.append(
            f'<div class="uvcell"><div class="uvhead">{f["id"]} · {f["surface_type"]} '
            f'{face_badges(f)} · tol {f["tolerance"]:.1e}<br><span class="dim">uv_bounds [{ub}]</span></div>'
            f'{svg_uv(f, pcs)}</div>')

    erows = "".join(
        f'<tr><td>{e["id"]}</td><td>{e["curve_type"]}</td>'
        f'<td>{"✓" if e["degenerate"] else ""}</td><td>{"✓" if e["closed"] else ""}</td>'
        f'<td>{"✓" if e["same_parameter"] else ""}</td>'
        f'<td>{len(e["pcurves"])}</td><td>{",".join(e["adjacent_faces"])}</td>'
        f'<td>{e["tolerance"]:.1e}</td></tr>'
        for e in geom.get("edges", []))
    vtol = [v["tolerance"] for v in geom.get("vertices", [])]
    vsum = (f'{len(vtol)} 顶点 · tol {min(vtol):.1e}…{max(vtol):.1e}' if vtol else "无顶点")
    etable = (
        '<table class="t"><tr><th>edge</th><th>curve_type</th><th>degen</th><th>closed</th>'
        '<th>sameP</th><th>#pc</th><th>faces</th><th>tol</th></tr>' + erows + '</table>')
    return f'<div class="uvrow">{"".join(uvs)}</div>', f'<div class="vsum">{vsum}</div>' + etable


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>geom review</title><style>
  body{{margin:0;background:#0f1115;color:#d8dee9;font:13px system-ui,sans-serif}}
  header{{padding:12px 16px;border-bottom:1px solid #232833}}
  header b{{color:#88c0d0}}
  .legend{{margin-top:5px;font-size:11px;color:#9aa4b2}}
  .sw{{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:middle;margin:0 4px 0 12px}}
  h2{{margin:14px 16px 2px;font-size:15px;color:#a3be8c}}
  .sub{{margin:0 16px 6px;font-size:11px;color:#7a8290}}
  .sec{{border-bottom:1px solid #1a1e26;padding-bottom:10px}}
  .cols{{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start;margin:0 12px}}
  .uvrow{{display:flex;gap:10px;flex-wrap:wrap}}
  .uvcell{{background:#0c0e12;border:1px solid #1a1e26;padding:4px}}
  .uvhead{{font-size:10px;color:#aeb5ab;margin:2px 4px 4px}}
  .dim{{color:#7a8290}}
  .badge{{background:#2a2f3a;color:#88c0d0;border-radius:3px;padding:0 4px;font-size:9px}}
  svg{{display:block}}
  .t{{border-collapse:collapse;margin:6px 16px;font-size:11px;font-family:ui-monospace,monospace}}
  .t th,.t td{{border:1px solid #232833;padding:2px 7px;text-align:left}}
  .t th{{color:#88c0d0}}
  .vsum{{margin:6px 16px;color:#9aa4b2;font-family:ui-monospace,monospace;font-size:11px}}
  .empty{{color:#7a8290;padding:20px}}
</style></head><body>
<header><b>occ-debug-mesh</b> · P0a geom 复查 · 3D + 参数空间(UV)
  <div class="legend">
    <span class="sw" style="background:#36d1c4"></span>普通 pcurve
    <span class="sw" style="background:#e74c3c"></span>缝边(两条)
    <span class="sw" style="background:#ff9f40"></span>退化/极点边(虚线)
    <span class="sw" style="background:#5a6b8c"></span>面网格
  </div>
</header>
{sections}
</body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="*.geom.json from occ-debug-mesh")
    ap.add_argument("--out", default="/tmp/occ-geom-view.html")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args(argv)

    secs = []
    for gpath in args.files:
        try:
            geom = json.load(open(gpath))
        except (OSError, ValueError) as exc:
            print(f"warning: {gpath}: {exc}", file=sys.stderr)
            continue
        mpath = gpath.replace(".geom.json", ".mesh.json")
        mesh = json.load(open(mpath)) if os.path.exists(mpath) else {}
        name = os.path.basename(gpath).replace(".geom.json", "")
        surfs = sorted({f["surface_type"] for f in geom.get("faces", [])})
        seam = sum(1 for e in geom.get("edges", []) for pc in e.get("pcurves", []) if pc["is_seam"])
        degen = sum(1 for e in geom.get("edges", []) if e["degenerate"])
        uvrow, tbl = tables(geom)
        secs.append(
            f'<section class="sec"><h2>{name}</h2>'
            f'<div class="sub">{len(geom.get("vertices",[]))} 顶点 · {len(geom.get("edges",[]))} 边 · '
            f'{len(geom.get("faces",[]))} 面 · surfaces={surfs} · seam-pcurves={seam} · degenerate={degen}</div>'
            f'<div class="cols">{svg_3d(mesh)}<div>{uvrow}</div></div>{tbl}</section>')

    if not secs:
        print("nothing to render", file=sys.stderr)
        return 1
    with open(args.out, "w") as fp:
        fp.write(PAGE.format(sections="\n".join(secs)))
    print(f"wrote {args.out}")
    if not args.no_open:
        import webbrowser
        webbrowser.open(f"file://{os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
