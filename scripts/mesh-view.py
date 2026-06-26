#!/usr/bin/env python3
"""Browser preview for occ-debug-mesh output (print-mesh JSON).

Renders each <name>.mesh.json as a self-contained inline-SVG isometric view:
faces as a faint mesh, and the discretized `edges[]` (the §7 feature) as bright
world-space polylines with their sample vertices marked. ZERO dependencies — no
CDN, no JS — so it renders in any browser, offline. One <section> per file,
stacked into a single dark page.

Complementary to scripts/occ_view.py (which renders the LLDB emitters' Plotly
JSON, a different shape and an interactive 3D widget).

    scripts/mesh-view.py a.mesh.json b.mesh.json      # write HTML + open browser
    scripts/mesh-view.py --no-open --out v.html *.json
"""
import argparse
import json
import math
import os
import sys
import webbrowser

# Distinct bright colors so adjacent edges read as separate polylines.
EDGE_COLORS = [
    "#ff7f0e", "#1f9bff", "#2ecc71", "#e74c3c", "#b07cff", "#1abc9c",
    "#f1c40f", "#ff5da2", "#7fd13b", "#ff9f40", "#36d1c4", "#ff6b6b",
]
_COS30, _SIN30 = math.cos(math.radians(30)), math.sin(math.radians(30))


def _iso(x, y, z):
    """Isometric projection, z up (SVG y grows down, so subtract z)."""
    return ((x - y) * _COS30, (x + y) * _SIN30 - z)


def _triples(flat):
    return [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3)]


def svg_for(mesh, target=560, pad=34):
    """One inline <svg> isometric view of a print-mesh: faint faces + bright edges."""
    faces = [(_triples(f["positions"]), f["indices"]) for f in mesh.get("faces", [])]
    edges = [_triples(e["points"]) for e in mesh.get("edges", [])]

    proj = [_iso(*p) for verts, _ in faces for p in verts]
    proj += [_iso(*p) for poly in edges for p in poly]
    if not proj:
        return '<div class="empty">（空形状：无面、无边）</div>'

    xs = [a for a, _ in proj]; ys = [b for _, b in proj]
    minx, miny = min(xs), min(ys)
    spanx, spany = max(max(xs) - minx, 1e-9), max(max(ys) - miny, 1e-9)
    scale = target / max(spanx, spany)
    W, H = spanx * scale + 2 * pad, spany * scale + 2 * pad

    def T(pt):
        sx, sy = _iso(*pt)
        return ((sx - minx) * scale + pad, (sy - miny) * scale + pad)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}">']
    # Faint face triangles (the surface mesh).
    for verts, idx in faces:
        for t in range(0, len(idx), 3):
            pts = " ".join(f"{X:.1f},{Y:.1f}" for X, Y in (T(verts[v]) for v in idx[t:t + 3]))
            out.append(f'<polygon points="{pts}" fill="#5a6b8c" fill-opacity="0.13" '
                       f'stroke="#5a6b8c" stroke-width="0.5"/>')
    # Bright discretized edges + their sample vertices (the §7 payload).
    for n, poly in enumerate(edges):
        col = EDGE_COLORS[n % len(EDGE_COLORS)]
        scr = [T(p) for p in poly]
        d = "M" + " L".join(f"{X:.1f},{Y:.1f}" for X, Y in scr)
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.6" '
                   f'stroke-linecap="round" stroke-linejoin="round"/>')
        out += [f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="2.4" fill="{col}"/>' for X, Y in scr]
    out.append("</svg>")
    return "\n".join(out)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>occ-debug-mesh preview</title>
<style>
  body{{margin:0;background:#0f1115;color:#d8dee9;font:14px system-ui,sans-serif}}
  header{{padding:14px 18px;border-bottom:1px solid #232833}}
  header b{{color:#88c0d0}} header span{{color:#7a8290}}
  .legend{{margin-top:6px;font-size:12px;color:#9aa4b2}}
  .swatch{{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:middle;margin:0 4px 0 12px}}
  h2{{margin:16px 18px 0;font-size:15px;color:#a3be8c}}
  .sub{{margin:2px 18px 8px;font-size:12px;color:#7a8290}}
  .sec{{border-bottom:1px solid #1a1e26;padding-bottom:12px}}
  .sec svg{{margin:0 14px}} .empty{{margin:10px 18px;color:#7a8290}}
</style></head><body>
<header>
  <b>occ-debug-mesh</b> <span>· print-mesh preview · 等距投影 (z 朝上) · 世界坐标</span>
  <div class="legend">
    <span class="swatch" style="background:#5a6b8c"></span>面网格 (半透明)
    <span class="swatch" style="background:#ff7f0e"></span>离散后的 edges[]（每色一条 = §7 产出）
  </div>
</header>
{sections}
</body></html>
"""

SECTION = '<section class="sec"><h2>{title}</h2><div class="sub">{sub}</div>{svg}</section>'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="*.mesh.json from occ-debug-mesh")
    ap.add_argument("--out", default="/tmp/occ-mesh-view.html", help="output HTML")
    ap.add_argument("--no-open", action="store_true", help="write HTML but don't open a browser")
    args = ap.parse_args(argv)

    sections = []
    for path in args.files:
        try:
            with open(path) as fp:
                mesh = json.load(fp)
        except (OSError, ValueError) as exc:
            print(f"warning: {path}: {exc}", file=sys.stderr)
            continue
        nf, ne = len(mesh.get("faces", [])), len(mesh.get("edges", []))
        nv = sum(len(e["points"]) // 3 for e in mesh.get("edges", []))
        partial = " · partial（有 failed face）" if mesh.get("partial") else ""
        sections.append(SECTION.format(
            title=os.path.basename(path),
            sub=f"{nf} 面 · {ne} 边 · {nv} 边采样点{partial}",
            svg=svg_for(mesh)))

    if not sections:
        print("nothing to render", file=sys.stderr)
        return 1
    with open(args.out, "w") as fp:
        fp.write(PAGE.format(sections="\n".join(sections)))
    print(f"wrote {args.out}")
    if not args.no_open:
        webbrowser.open(f"file://{os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
