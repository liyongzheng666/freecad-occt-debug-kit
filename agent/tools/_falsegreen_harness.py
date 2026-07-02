"""FreeCAD 侧假绿判别 harness（falsegreen_probe）：支撑面类型 + 缺陷端局部性。

由 falsegreen_probe.py 经 FreeCADCmd 跑（**不是 agent 包的一部分**）。env：
  FG_CASE         case 几何（box/box-flat/wedge/pocket 或 brep:/step:/file: 路径）
  FG_EDGES        可选，逗号 1-based blend 目标边号；空 = 全部边
  FG_RESULT_BREP  假绿结果 BREP（reproduce 的 bad_shape）
  FG_FACE_IDS     可选，逗号 defect face 号（check_valid 的 ref.face_id，如 "F1,F5"；
                  约定 F# = 结果 shape.Faces 1-based 枚举序——已实证 E7 F5=end-cap 小面）
  FG_OUT_JSON     结果 JSON

输出（全为判别量，裁定在 agent 侧 investigate._fg_* 纯函数）：
  support_types    blend 边的支撑面类型名集合（如 ["Plane","BSplineSurface"]）
  free_ends        自由端点列表 [[x,y,z]]——blend 边端点中**不与其它 blend 边共享**的
                   端点（S4 端盖判别的前置：全边/闭链 blend 无自由端，端盖机器不参与）
  defect_locality  [{fid, surf, d_end, d_mid}]——defect 面到最近自由端 / 到边中点距离
print() 只 ASCII。
"""
import json
import os

import Part
import FreeCAD as App
V = App.Vector


def build_shape(case):
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


def main():
    out = os.environ["FG_OUT_JSON"]
    case = os.environ["FG_CASE"]
    edges_env = os.environ.get("FG_EDGES")
    result_brep = os.environ.get("FG_RESULT_BREP")
    face_ids = [x.strip() for x in os.environ.get("FG_FACE_IDS", "").split(",") if x.strip()]

    shape = build_shape(case)
    blended0 = ([int(x) - 1 for x in edges_env.split(",") if x.strip()]
                if edges_env else list(range(len(shape.Edges))))

    # 支撑面类型（blend 边两侧面的 Surface 类型名，去重）
    support = set()
    for i in blended0:
        e = shape.Edges[i]
        for f in shape.Faces:
            if any(te.isSame(e) for te in f.Edges):
                support.add(type(f.Surface).__name__)

    # 自由端：blend 边端点中不与其它 blend 边共享的（端盖机器只在这里参与）
    def vkey(p):
        return (round(p.x, 6), round(p.y, 6), round(p.z, 6))
    counts = {}
    for i in blended0:
        for v in shape.Edges[i].Vertexes:
            counts[vkey(v.Point)] = counts.get(vkey(v.Point), 0) + 1
    free_ends = [list(k) for k, n in counts.items() if n == 1]
    mids = [shape.Edges[i].valueAt((shape.Edges[i].FirstParameter + shape.Edges[i].LastParameter) / 2)
            for i in blended0]

    # 缺陷端局部性（在结果 shape 上量）
    locality = []
    if result_brep and face_ids and os.path.exists(result_brep):
        rs = Part.Shape()
        rs.read(result_brep)
        for fid in face_ids:
            try:
                f = rs.Faces[int(fid[1:]) - 1]
                d_end = (min(f.distToShape(Part.Vertex(V(*p)))[0] for p in free_ends)
                         if free_ends else None)
                d_mid = min(f.distToShape(Part.Vertex(p))[0] for p in mids) if mids else None
                locality.append({"fid": fid, "surf": type(f.Surface).__name__,
                                 "d_end": (None if d_end is None else round(d_end, 4)),
                                 "d_mid": (None if d_mid is None else round(d_mid, 4))})
            except Exception as ex:                          # 面号越界/量距失败：照实记错，不猜
                locality.append({"fid": fid, "error": type(ex).__name__ + ": " + str(ex)[:60]})

    with open(out, "w") as fp:
        json.dump({"support_types": sorted(support), "free_ends": free_ends,
                   "n_blended": len(blended0), "defect_locality": locality}, fp, ensure_ascii=False)
    print("[falsegreen] support=%s free_ends=%d defects=%d"
          % (sorted(support), len(free_ends), len(locality)))


main()
