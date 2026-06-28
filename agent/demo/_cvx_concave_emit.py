"""FreeCAD 侧：凸/凹圆角对照几何 → Print 事件（两支撑面 + 共享棱 + 两面外法向箭头 + 滚球 + note）。

由 convex_concave_demo.py 经 FreeCADCmd 跑（**不是 agent 包的一部分**）。
凸/凹判据（穿过实体材料的二面角）：
  凸 convex  : 材料夹角 <180°；滚球在【材料内侧】削棱；两面外法向【背着球岔开】。sign=-1。
  凹 concave : 材料夹角 >180°(内角)；滚球卡在【缺口空腔】填角；两面外法向【对冲指向球】。sign=+1。
注意：print() 只用 ASCII（FreeCADCmd stdout 不收中文）；note 的 message 是 JSON，可中文。
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import occ_capture as cap  # noqa: E402  复用 flock 追加 + run/seq

import Part  # noqa: E402  FreeCAD
import FreeCAD as App  # noqa: E402
V = App.Vector

SESSION = Path(os.environ.get("OCC_DEBUG_SESSION", str(REPO / ".occ-debug" / "sessions" / "cvx-demo")))
(SESSION / "assets").mkdir(parents=True, exist_ok=True)

R = 2.0
TEAL, BLUE, RED, YEL, ORANGE = "#5bc0be", "#6a9bd8", "#ff5d5d", "#ffd24a", "#e0883a"


def emit_shape(shape, ent_id, group, label, color, opacity=0.45):
    run_id = cap._run_id(SESSION)
    rel = run_id + "/" + ent_id.replace("/", "_") + ".brep"
    p = SESSION / "assets" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    shape.exportBrep(str(p))
    bb = shape.BoundBox
    cap._append(SESSION, op="add", id=ent_id, group=group, kind="shape", label=label,
                geometry={"bbox": {"min": [bb.XMin, bb.YMin, bb.ZMin], "max": [bb.XMax, bb.YMax, bb.ZMax]}},
                asset={"format": "occt-brep", "path": rel}, style={"color": color, "opacity": opacity})


def emit_vector(origin, direction, ent_id, group, label, color, length=4.0):
    cap._append(SESSION, op="add", id=ent_id, group=group, kind="vector", label=label,
                geometry={"origin": list(origin), "direction": list(direction), "length": length},
                style={"color": color})


def emit_edge(p0, p1, ent_id, group, label, color):
    cap._append(SESSION, op="add", id=ent_id, group=group, kind="polyline", label=label,
                geometry={"points": [list(p0), list(p1)]}, style={"color": color, "line_width": 8})


def emit_ball(center, ent_id, group, label, color, radius, opacity=0.55):
    # 实心球：用 point kind（viewer 直接 SphereGeometry(size=radius) 渲染，不走网格资产异步换图）。
    cap._append(SESSION, op="add", id=ent_id, group=group, kind="point", label=label,
                geometry={"position": list(center)},
                style={"color": color, "size": radius, "opacity": opacity})


def note(msg):
    cap._append(SESSION, op="note", level="info", message=msg)


def adjacent_faces(solid, x, y):
    """两顶点都落在竖线 (x,y) 上的那条棱 + 它的两张相邻面。"""
    edge = None
    for e in solid.Edges:
        vs = e.Vertexes
        if len(vs) == 2 and all(abs(v.X - x) < 1e-6 and abs(v.Y - y) < 1e-6 for v in vs):
            edge = e
            break
    faces = [f for f in solid.Faces if any(te.isSame(edge) for te in f.Edges)] if edge else []
    return faces


def scene(solid, edge_xy, n1, n2, sign, group, tag):
    x, y = edge_xy
    mid = (x, y, 5.0)
    faces = adjacent_faces(solid, x, y)
    for i, f in enumerate(faces[:2]):
        emit_shape(f, group + "/face%d" % (i + 1), group, tag + " support face %d" % (i + 1),
                   [TEAL, BLUE][i], opacity=0.5)
    emit_edge((x, y, 0.0), (x, y, 10.0), group + "/edge", group, tag + " shared edge", RED)
    emit_vector(mid, n1, group + "/n1", group, tag + " outward normal 1", YEL)
    emit_vector(mid, n2, group + "/n2", group, tag + " outward normal 2", YEL)
    cc = (mid[0] + sign * R * (n1[0] + n2[0]),
          mid[1] + sign * R * (n1[1] + n2[1]),
          mid[2] + sign * R * (n1[2] + n2[2]))
    emit_ball(cc, group + "/ball", group, tag + " rolling ball r=%.1f" % R, ORANGE, R)


# 清场：每次 run 用相同 id，先清掉上一 run 的对象，避免 reducer 的"重复 ID"拒绝
cap._append(SESSION, op="clear_scene", include_protected=True)

# ── 凸：方块外棱 90°，球在材料内侧削棱，外法向 +x / -y（背着球岔开）──
note("【凸圆角 convex】方块外棱(材料夹角90°<180°)：两面外法向【岔开】(背着材料/背着球)；"
     "滚球 r=2 在【材料内侧】(8,2,5)，把尖棱削圆。")
scene(Part.makeBox(10, 10, 10), (10.0, 0.0), (1, 0, 0), (0, -1, 0), -1, "convex", "convex")

# ── 凹：L 形内角 90°，球在缺口空腔填角，外法向 +x / +y（对冲指向球）──
L = Part.makeBox(5, 20, 10, V(20, 0, 0)).fuse(Part.makeBox(20, 5, 10, V(20, 0, 0)))
note("【凹圆角 concave】L 形内角(材料夹角270°>180°)：两面外法向【对冲指向缺口=指向球】；"
     "滚球 r=2 卡在【缺口空腔】(27,7,5)，把内角填圆。")
scene(L, (25.0, 5.0), (1, 0, 0), (0, 1, 0), +1, "concave", "concave")

# ── 凹 + 大半径【失败】：窄槽宽4，r=3 → 直径6>4，球塞不进底角（StdFail_NotDone，实测）──
G = "concave-fail"
chan = Part.makeBox(20, 12, 10, V(50, 0, 0)).cut(Part.makeBox(4, 14, 6, V(58, -1, 6)))  # 槽 x[58,62]
emit_shape(chan, G + "/solid", G, "slot block (width 4)", "#8a93a8", opacity=0.22)
emit_edge((58, 0, 6), (58, 12, 6), G + "/edgeL", G, "inner bottom edge @ left wall", RED)
emit_edge((62, 0, 6), (62, 12, 6), G + "/edgeR", G, "inner bottom edge @ right wall", RED)
mid = (58.0, 6.0, 6.0)
emit_vector(mid, (0, 0, 1), G + "/n1", G, "floor outward normal", YEL)   # 楼板法向 +z（指向球）
emit_vector(mid, (1, 0, 0), G + "/n2", G, "left-wall outward normal", YEL)  # 左墙法向 +x（指向球）
RF = 3.0
cc = (58.0 + RF, 6.0, 6.0 + RF)  # (61,6,9)：坐左底角 → 右伸到 x=64，穿过右墙 x=62
emit_ball(cc, G + "/ball", G,
          "ball r=3 (diam 6 > slot 4 -> cannot fit; pokes through right wall x=62)", "#ff4d4d", RF, opacity=0.5)
note("【凹+大半径 失败】窄槽宽4：内角是凹的，但 r=3→直径6 > 槽宽4，滚球塞不进底角"
     "(红球右半穿过对面墙 x=62)→ makeFillet 抛 StdFail_NotDone。对比同槽 r≤2 能成。")

note("对照口诀：法向【岔开】=凸(削棱,球在料内)；法向【对冲指向球】=凹(填角,球在空腔)；"
     "凹但半径过大→直径>可用宽度→球塞不进→失败。")
print("[cvx-concave] emitted convex(x0-10) + concave-ok(x20-40) + concave-fail(x50-70)")
