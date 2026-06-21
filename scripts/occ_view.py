#!/usr/bin/env python3
"""Standalone viewer for the JSON the OCCT LLDB emitters write.

The `occ_viz_*` LLDB commands (scripts/lldb_occt_formatters.py) write
/tmp/occ_dv_<var>.json in Plotly's native data/layout shape.  Debug Visualizer
is only one consumer of those files — and a fragile one (see the troubleshooting
table in docs/occt-debugging.md).  This script renders the very same JSON in a
normal browser, with zero dependency on VS Code or the DAP evaluate channel.

Usage
-----
    scripts/occ_view.py                 # all /tmp/occ_dv_*.json
    scripts/occ_view.py Spine           # /tmp/occ_dv_Spine.json
    scripts/occ_view.py Spine Vtx       # overlay both in ONE 3D plot
    scripts/occ_view.py /path/to.json   # an explicit file
    scripts/occ_view.py Spine --no-open # write HTML, don't launch a browser

Every plotly-kind file passed is overlaid into a single figure, so this is the
robust way to compare a curve `cv` against a STEP solid: emit each (e.g.
`occ_viz_pt_curve pt cv` and a shape emitter), then `occ_view.py cv <shape>`.
Graph-kind (topology DAG) and text-kind payloads are rendered too.
"""

import argparse
import glob
import json
import os
import sys
import webbrowser

DV_DIR = "/tmp"
DEFAULT_OUT = "/tmp/occ_view.html"

# Distinct fallback colors so overlaid traces that didn't set their own color
# stay separable.  Mirrors the palette in lldb_occt_formatters._DV_COLORS.
_COLORS = [
    "crimson", "steelblue", "seagreen", "darkorange",
    "mediumpurple", "teal", "goldenrod", "deeppink",
]


def _resolve(arg):
    """Map a CLI argument to a JSON path: a real path, or a var name."""
    if os.path.sep in arg or arg.endswith(".json"):
        return arg
    return os.path.join(DV_DIR, f"occ_dv_{arg}.json")


def _load(paths):
    """Read each path, returning (label, payload) pairs; warn on failures."""
    loaded = []
    for path in paths:
        label = os.path.basename(path)
        if label.startswith("occ_dv_") and label.endswith(".json"):
            label = label[len("occ_dv_"):-len(".json")]
        try:
            with open(path) as fp:
                loaded.append((label, json.load(fp)))
        except FileNotFoundError:
            print(f"warning: {path} not found — run an occ_viz_* command first",
                  file=sys.stderr)
        except (OSError, ValueError) as exc:
            print(f"warning: {path}: {exc}", file=sys.stderr)
    return loaded


def _kind(payload):
    k = payload.get("kind", {})
    for name in ("plotly", "graph", "text"):
        if k.get(name):
            return name
    return "unknown"


def build_sections(loaded):
    """Group payloads into render sections; overlay all plotly files into one."""
    plotly_traces, plotly_titles, sections = [], [], []
    color_i = 0
    for label, payload in loaded:
        kind = _kind(payload)
        if kind == "plotly":
            for trace in payload.get("data", []):
                trace.setdefault("name", label)
                # Give traces lacking an explicit color a stable distinct one.
                marker = trace.setdefault("marker", {})
                if "color" not in marker and "line" not in trace:
                    marker["color"] = _COLORS[color_i % len(_COLORS)]
                    color_i += 1
                plotly_traces.append(trace)
            title = payload.get("layout", {}).get("title")
            plotly_titles.append(title if isinstance(title, str) and title else label)
        elif kind == "graph":
            sections.append({
                "kind": "graph", "title": label,
                "nodes": payload.get("nodes", []), "edges": payload.get("edges", []),
            })
        elif kind == "text":
            sections.append({
                "kind": "text", "title": label,
                "text": payload.get("text", ""),
            })
        else:
            sections.append({
                "kind": "text", "title": label,
                "text": "unrecognized payload:\n" + json.dumps(payload, indent=2),
            })

    if plotly_traces:
        sections.insert(0, {
            "kind": "plotly",
            "title": " & ".join(plotly_titles),
            "data": plotly_traces,
            "layout": {"title": " & ".join(plotly_titles)},
        })
    return sections


_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>OCCT view</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body{{margin:0;background:#0f1115;color:#d8dee9;font:14px system-ui,sans-serif}}
  h2{{margin:12px 16px 4px;font-size:15px;font-weight:600;color:#88c0d0}}
  .sec{{margin:0 8px 18px}}
  .plot{{height:78vh}} .graph{{height:60vh;border:1px solid #2a2f3a}}
  pre{{margin:8px 16px;padding:12px;background:#1a1d24;border-radius:6px;white-space:pre-wrap}}
  .empty{{margin:24px 16px;color:#7a8290}}
</style></head><body>
<div id="root"></div>
<script>
const SECTIONS = {payload};
const DARK = {{paper_bgcolor:'#0f1115',plot_bgcolor:'#0f1115',font:{{color:'#d8dee9'}}}};
const root = document.getElementById('root');
if (!SECTIONS.length) {{
  root.innerHTML = '<p class="empty">No data. Run an occ_viz_* command, then re-run occ_view.py.</p>';
}}
SECTIONS.forEach((s, i) => {{
  const sec = document.createElement('div'); sec.className = 'sec';
  const h = document.createElement('h2'); h.textContent = (s.kind === 'plotly' ? '3D · ' : '') + s.title;
  sec.appendChild(h); root.appendChild(sec);
  if (s.kind === 'plotly') {{
    const d = document.createElement('div'); d.className = 'plot'; d.id = 'p'+i; sec.appendChild(d);
    const layout = Object.assign({{}}, DARK, s.layout || {{}});
    Plotly.newPlot(d, s.data, layout, {{responsive:true}});
  }} else if (s.kind === 'graph') {{
    const d = document.createElement('div'); d.className = 'graph'; d.id = 'g'+i; sec.appendChild(d);
    new vis.Network(d, {{
      nodes: new vis.DataSet(s.nodes.map(n => ({{id:n.id, label:n.label}}))),
      edges: new vis.DataSet(s.edges.map(e => ({{from:e.from, to:e.to, label:e.label, arrows:'to'}}))),
    }}, {{
      nodes:{{shape:'box',color:{{background:'#2e3440',border:'#88c0d0'}},font:{{color:'#eceff4'}}}},
      edges:{{color:'#4c566a',font:{{color:'#a3be8c',size:11}}}},
      layout:{{hierarchical:{{direction:'UD',sortMethod:'directed'}}}},
    }});
  }} else {{
    const pre = document.createElement('pre'); pre.textContent = s.text; sec.appendChild(pre);
  }}
}});
</script></body></html>
"""


def render(sections, out_path):
    # Inline the JSON; neutralize any "</script>" that could close the tag early.
    payload = json.dumps(sections).replace("</", "<\\/")
    with open(out_path, "w") as fp:
        fp.write(_HTML.format(payload=payload))
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vars", nargs="*",
                    help="var names (-> /tmp/occ_dv_<name>.json) or explicit paths; "
                         "default: all /tmp/occ_dv_*.json")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"output HTML (default {DEFAULT_OUT})")
    ap.add_argument("--no-open", action="store_true", help="write HTML but do not launch a browser")
    args = ap.parse_args(argv)

    if args.vars:
        paths = [_resolve(v) for v in args.vars]
    else:
        paths = sorted(glob.glob(os.path.join(DV_DIR, "occ_dv_*.json")))
        if not paths:
            print("no /tmp/occ_dv_*.json files — run an occ_viz_* command first",
                  file=sys.stderr)
            return 1

    loaded = _load(paths)
    if not loaded:
        return 1

    out = render(build_sections(loaded), args.out)
    print(f"wrote {out}")
    if not args.no_open:
        webbrowser.open(f"file://{os.path.abspath(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
