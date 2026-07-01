"""FreeCAD 侧输入预检 harness（triage）：算 case 每条边的二面角(近切度) + 支撑面曲率半径。

由 triage_input.py 经 FreeCADCmd 跑（**不是 agent 包的一部分**）。env：
  TRIAGE_CASE       case 几何（box / box-flat / wedge / pocket）或 brep:/step:/file: 路径（G26）
  TRIAGE_OUT_JSON   结果 JSON
  TRIAGE_EDGE_INDEX 可选，1-based 边号（G26 单边聚焦）；设了则只报该边的二面角/曲率，
                    不设则对全 shape 聚合（合成 case 现状，向后兼容）

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
    # G26：case 带 brep:/step:/file: 前缀 → 从磁盘读整个 shape（与 _fillet_harness 同分支，
    # 两 harness 各留一份，见计划设计基线②）。绝对路径。
    scheme = case.split(":", 1)[0]
    if scheme in ("brep", "step", "file"):
        s = Part.Shape()
        s.read(case.split(":", 1)[1])
        return s
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
    focus_env = os.environ.get("TRIAGE_EDGE_INDEX")   # G26：1-based 单边聚焦；None=全 shape 聚合
    focus0 = (int(focus_env) - 1) if focus_env else None   # → 0-based，对齐 per["edge"]
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
                    "support_curv_radius": (None if r == float("inf") else round(r, 3)),
                    "curv_face": (fidx[0] if r0 <= r1 else fidx[1]) if r != float("inf") else None})
        min_dih = min(min_dih, d)                # 聚合路径：原逻辑逐位不变（未 round 累积，输出时才 round）
        if r < min_rad:
            min_rad = r
            min_rad_face = fidx[0] if r0 <= r1 else fidx[1]

    if focus0 is not None:
        # G26 单边聚焦：per 是过滤过的列表（<2 支撑面的边被 continue），故按 p["edge"] 匹配、
        # 绝不能 per[N-1]。miss（该边 <2 支撑面/越界）→ 诚实空报告，不抛。
        sel = next((p for p in per if p["edge"] == focus0), None)
        if sel is not None:
            picked = [sel]
            min_dih = sel["dihedral_deg"]
            min_r = sel["support_curv_radius"]          # 已是 None 或 round 值
            min_rad_face = sel["curv_face"]
        else:
            picked = []
            min_dih = 180.0
            min_r = None
            min_rad_face = None
        result = {
            "case": case,
            "focus_edge": focus_env,                    # 1-based，回声
            "focus_miss": sel is None,
            "n_edges": len(per),
            "min_dihedral_deg": min_dih,
            "near_tangent_edges": [p for p in picked if p["dihedral_deg"] < 10.0],
            "min_support_curv_radius": min_r,
            "min_support_curv_face": min_rad_face,
        }
    else:
        result = {                                       # 聚合路径：与 G26 前逐位一致
            "case": case,
            "n_edges": len(per),
            "min_dihedral_deg": round(min_dih, 3),
            "near_tangent_edges": [p for p in per if p["dihedral_deg"] < 10.0],
            "min_support_curv_radius": (None if min_rad == float("inf") else round(min_rad, 3)),
            "min_support_curv_face": min_rad_face,
        }
    with open(out, "w") as fp:
        json.dump(result, fp, ensure_ascii=False)
    print("[triage] case=%s edges=%d focus=%s min_dihedral=%.2f min_curv=%s"
          % (case, len(per), focus_env or "-", result["min_dihedral_deg"], result["min_support_curv_radius"]))


main()
