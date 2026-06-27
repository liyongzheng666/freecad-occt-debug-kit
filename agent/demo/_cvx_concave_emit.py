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
                geometry={"points": [list(p0), list(p1)]}, style={"color": color, "line_width": 6})


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
    emit_shape(Part.makeSphere(R, V(*cc)), group + "/ball", group,
               tag + " rolling ball r=%.1f" % R, ORANGE, opacity=0.4)


# ── 凸：方块外棱 90°，球在材料内侧削棱，外法向 +x / -y（背着球岔开）──
note("【凸圆角 convex】方块外棱(材料夹角90°<180°)：两面外法向【岔开】(背着材料/背着球)；"
     "滚球 r=2 在【材料内侧】(8,2,5)，把尖棱削圆。")
scene(Part.makeBox(10, 10, 10), (10.0, 0.0), (1, 0, 0), (0, -1, 0), -1, "convex", "convex")

# ── 凹：L 形内角 90°，球在缺口空腔填角，外法向 +x / +y（对冲指向球）──
L = Part.makeBox(5, 20, 10, V(20, 0, 0)).fuse(Part.makeBox(20, 5, 10, V(20, 0, 0)))
note("【凹圆角 concave】L 形内角(材料夹角270°>180°)：两面外法向【对冲指向缺口=指向球】；"
     "滚球 r=2 卡在【缺口空腔】(27,7,5)，把内角填圆。")
scene(L, (25.0, 5.0), (1, 0, 0), (0, 1, 0), +1, "concave", "concave")

note("对照口诀：法向【岔开】=凸(削棱,球在料内)；法向【对冲指向球】=凹(填角,球在空腔)。")
print("[cvx-concave] emitted convex(left ~x0-10) + concave(right ~x20-40)")
