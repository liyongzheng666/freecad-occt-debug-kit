"""FreeCAD 侧输入预检 harness（triage）：算 case 每条边的二面角(近切度) + 支撑面曲率半径
+ 输入质量四项（P1.3：凹凸 / 短边 / sliver 面 / 容差离群）。

由 triage_input.py 经 FreeCADCmd 跑（**不是 agent 包的一部分**）。env：
  TRIAGE_CASE       case 几何（box / box-flat / wedge / pocket）或 brep:/step:/file: 路径（G26）
  TRIAGE_OUT_JSON   结果 JSON
  TRIAGE_EDGE_INDEX 可选，1-based 边号（G26 单边聚焦）；设了则只报该边的二面角/曲率，
                    不设则对全 shape 聚合（合成 case 现状，向后兼容）
  TRIAGE_EDGES      可选，逗号 1-based 多边号（P2.2 vertex_probe）：目标 blend 边集；
                    不设 → 视为全部边被 blend（与 _fillet_harness 无 REPRO_EDGES 语义一致）

输出 {min_dihedral_deg, near_tangent_edges, min_support_curv_radius, n_edges}
+ 输入质量四键 {convexity, short_edges, sliver_faces, tolerance_outliers}（P1.3，两路径都带；
只作报告与证据，**不进 S0/S2 判别逻辑**——判别语义不动是硬约束）。
判别用途（见 playbook fillet-failures.json 的失效四态）：
  min_dihedral 小 → 支撑面近切 → S2 geometric(近切型)；
  fillet_r > min_support_curv_radius → S2 geometric(曲率型，球比凹曲率大)；
  都不沾且 overflow → S2 algorithmic(两带重叠)/face(单带溢出)。
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


# ---- P1.3 输入质量四项（只报告，不进判别） -----------------------------------

_PROBE_N = 16                    # 角占率探针采样数（22.5deg 分辨率，凸0.25/凹0.75 margin 充足）


def _edge_convexity(shape, e, mid, eps):
    """带符号凹凸：方向无关的角占率探针。

    计划原案"沿 (n1+n2) 偏移 isInside"不可判别——外法线角平分线对凸/凹边都指向材料外。
    改用：边中点垂直平面上取 _PROBE_N 个半径 eps 的圆点，isInside 占率 ~= 材料楔角/360
    （凸边 90deg -> ~0.25，凹边 270deg -> ~0.75），无需任何 face/edge 朝向推理。
    近切/退化/非实体 -> "unknown"（诚实，不硬猜）。
    """
    try:
        tp = (e.FirstParameter + e.LastParameter) / 2.0
        t = e.tangentAt(tp)
        if t.Length < 1e-12:
            return "unknown"
        t.normalize()
        a = V(1, 0, 0) if abs(t.x) < 0.9 else V(0, 1, 0)
        b1 = t.cross(a)
        b1.normalize()
        b2 = t.cross(b1)
        b2.normalize()
        inside = 0
        for k in range(_PROBE_N):
            ang = 2.0 * math.pi * k / _PROBE_N
            p = mid + (b1 * math.cos(ang) + b2 * math.sin(ang)) * eps
            if shape.isInside(p, 1e-7, False):
                inside += 1
        frac = inside / float(_PROBE_N)
        if frac < 0.35:
            return "convex"
        if frac > 0.65:
            return "concave"
        return "unknown"          # ~0.5：切向/平齐/探针歧义
    except Exception:
        return "unknown"


def _vertex_report(shape, blended0, convexity):
    """P2.2/S4：目标 blend 边端点的顶点构型。

    对每个唯一顶点数 incident 边；报告"至少 1 条 blend 边落脚"的顶点：
    {vertex, n_edges, n_blended, convexity_mix}。判定（vertex_c 构型）在 agent 侧
    （investigate._vertex_verdict 纯函数），harness 只出数据。
    """
    out = []
    for k, v in enumerate(shape.Vertexes):
        try:
            incident = [i for i, e in enumerate(shape.Edges)
                        if any(v.isSame(ve) for ve in e.Vertexes)]
        except Exception:
            continue
        blended_here = [i for i in incident if i in blended0]
        if not blended_here:
            continue
        mix = sorted({convexity.get(str(i), "unknown") for i in incident})
        out.append({"vertex": k, "n_edges": len(incident),
                    "n_blended": len(blended_here), "convexity_mix": mix})
    return out


def _input_quality(shape, thin_eps):
    """短边 / sliver 面 / 容差离群（全 shape 一次性扫描；convexity 在主循环逐边算）。"""
    short_edges = []
    for i, e in enumerate(shape.Edges):
        try:
            if e.Length < thin_eps:
                short_edges.append([i, round(e.Length, 6)])
        except Exception:
            continue
    sliver_faces = []
    for j, f in enumerate(shape.Faces):
        try:
            peri = sum(fe.Length for fe in f.Edges)
            if peri <= 0:
                continue
            width = 2.0 * f.Area / peri          # 细长面宽度估计
            if width < thin_eps:
                sliver_faces.append([j, round(width, 6)])
        except Exception:
            continue
    tolerance_outliers = []
    try:
        tols = []                                # [kind, idx, tol]
        for kind, subs in (("vertex", shape.Vertexes), ("edge", shape.Edges), ("face", shape.Faces)):
            for k, s in enumerate(subs):
                tol = getattr(s, "Tolerance", None)
                if tol is not None and tol > 0:
                    tols.append([kind, k, float(tol)])
        if tols:
            vals = sorted(t[2] for t in tols)
            med = vals[len(vals) // 2]
            if med > 0:
                tolerance_outliers = [[k, i, t] for (k, i, t) in tols if t > 10.0 * med]
    except Exception:
        tolerance_outliers = []
    return short_edges, sliver_faces, tolerance_outliers


def main():
    case = os.environ.get("TRIAGE_CASE", "box")
    out = os.environ["TRIAGE_OUT_JSON"]
    focus_env = os.environ.get("TRIAGE_EDGE_INDEX")   # G26：1-based 单边聚焦；None=全 shape 聚合
    focus0 = (int(focus_env) - 1) if focus_env else None   # → 0-based，对齐 per["edge"]
    shape = build_shape(case)

    # P1.3 阈值：探针半径 / 细长判据都挂 bbox 对角线（尺度无关），并与容差下限钳住
    diag = shape.BoundBox.DiagonalLength if shape.BoundBox.isValid() else 1.0
    probe_eps = min(max(1e-3 * diag, 1e-5), 1.0)
    thin_eps = max(1e-3 * diag, 1e-4)

    per = []
    convexity = {}                               # P1.3：edge_i(str) -> convex|concave|unknown（只报告）
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
        convexity[str(i)] = _edge_convexity(shape, e, mid, probe_eps)
        min_dih = min(min_dih, d)                # 聚合路径：原逻辑逐位不变（未 round 累积，输出时才 round）
        if r < min_rad:
            min_rad = r
            min_rad_face = fidx[0] if r0 <= r1 else fidx[1]

    short_edges, sliver_faces, tolerance_outliers = _input_quality(shape, thin_eps)
    # P2.2：blend 目标边集（TRIAGE_EDGES 逗号 1-based；不设=全部边，与 _fillet_harness 语义一致）
    edges_env = os.environ.get("TRIAGE_EDGES")
    blended0 = ({int(x) - 1 for x in edges_env.split(",") if x.strip()}
                if edges_env else set(range(len(shape.Edges))))
    quality = {"convexity": convexity, "short_edges": short_edges,
               "sliver_faces": sliver_faces, "tolerance_outliers": tolerance_outliers,
               "vertex_report": _vertex_report(shape, blended0, convexity)}

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
            **quality,                                  # P1.3：输入质量为全 shape 属性，聚焦路径也带全量
        }
    else:
        result = {                                       # 聚合路径：判别键与 G26 前逐位一致，仅增 P1.3 报告键
            "case": case,
            "n_edges": len(per),
            "min_dihedral_deg": round(min_dih, 3),
            "near_tangent_edges": [p for p in per if p["dihedral_deg"] < 10.0],
            "min_support_curv_radius": (None if min_rad == float("inf") else round(min_rad, 3)),
            "min_support_curv_face": min_rad_face,
            **quality,
        }
    with open(out, "w") as fp:
        json.dump(result, fp, ensure_ascii=False)
    print("[triage] case=%s edges=%d focus=%s min_dihedral=%.2f min_curv=%s"
          % (case, len(per), focus_env or "-", result["min_dihedral_deg"], result["min_support_curv_radius"]))


main()
