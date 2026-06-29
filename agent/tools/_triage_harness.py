"""FreeCAD 侧输入预检 harness（triage）：算 case 每条边的二面角(近切度) + 支撑面曲率半径。

由 triage_input.py 经 FreeCADCmd 跑（**不是 agent 包的一部分**）。env：
  TRIAGE_CASE      case 几何（box / box-flat / wedge / pocket）
  TRIAGE_OUT_JSON  结果 JSON

输出 {min_dihedral_deg, near_tangent_edges, min_support_curv_radius, n_edges}。
判别用途（见 playbook fillet-failures.json 的失效三态）：
  min_dihedral 小 → 支撑面近切 → S2 geometric(近切型)；
  fillet_r > min_support_curv_radius → S2 geometric(曲率型，球比凹曲率大)；
  都不沾且 overflow → S2 algorithmic(两圆角重叠，可 SSI 互裁)。
print() 只 ASCII。
"""
import json
import math
import os

import Part
import FreeCAD as App
V = App.Vector


def build_shape(case):
    if case == "box":
        return Part.makeBox(10, 20, 30)
    if case == "box-flat":
        return Part.makeBox(30, 20, 2)
    if case == "wedge":
        pts = [V(0, 0, 0), V(20, 0, 0), V(20, 0, 0.6)]
        return Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 8, 0))
    if case == "pocket":
        return Part.makeBox(16, 16, 10).cut(Part.makeCylinder(3, 8, V(8, 8, 3)))
    raise ValueError("unknown case " + str(case))


def _normal(face, pt):
    u, v = face.Surface.parameter(pt)
    return face.Surface.normal(u, v)


def _dihedral(f1, f2, pt):
    n1, n2 = _normal(f1, pt), _normal(f2, pt)
    c = abs(n1.dot(n2)) / (n1.Length * n2.Length)
    return math.degrees(math.acos(min(1.0, max(-1.0, c))))


def _curv_radius(face):
    s = face.Surface
    if isinstance(s, Part.Cylinder):
        return float(s.Radius)
    if isinstance(s, Part.Sphere):
        return float(s.Radius)
    return float("inf")          # 平面/其它：无曲率约束


def main():
    case = os.environ.get("TRIAGE_CASE", "box")
    out = os.environ["TRIAGE_OUT_JSON"]
    shape = build_shape(case)

    per = []
    min_dih = 180.0
    min_rad = float("inf")
    min_rad_face = None                          # 最小凹曲率支撑面的 shape.Faces 序号（曲率型失效现场）
    for i, e in enumerate(shape.Edges):
        fidx = [j for j, f in enumerate(shape.Faces) if any(te.isSame(e) for te in f.Edges)]
        if len(fidx) < 2:
            continue
        f0, f1 = shape.Faces[fidx[0]], shape.Faces[fidx[1]]
        mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
        try:
            d = _dihedral(f0, f1, mid)
        except Exception:
            continue
        r0, r1 = _curv_radius(f0), _curv_radius(f1)
        r = min(r0, r1)
        per.append({"edge": i, "dihedral_deg": round(d, 3),
                    "support_curv_radius": (None if r == float("inf") else round(r, 3))})
        min_dih = min(min_dih, d)
        if r < min_rad:
            min_rad = r
            min_rad_face = fidx[0] if r0 <= r1 else fidx[1]

    result = {
        "case": case,
        "n_edges": len(per),
        "min_dihedral_deg": round(min_dih, 3),
        "near_tangent_edges": [p for p in per if p["dihedral_deg"] < 10.0],
        "min_support_curv_radius": (None if min_rad == float("inf") else round(min_rad, 3)),
        "min_support_curv_face": min_rad_face,
    }
    with open(out, "w") as fp:
        json.dump(result, fp, ensure_ascii=False)
    print("[triage] case=%s edges=%d min_dihedral=%.2f min_curv=%s"
          % (case, len(per), result["min_dihedral_deg"], result["min_support_curv_radius"]))


main()
