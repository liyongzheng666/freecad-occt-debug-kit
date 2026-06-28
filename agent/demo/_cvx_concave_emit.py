"""FreeCAD 侧：凸/凹圆角对照 → Print 事件。用【真实圆角面】表示圆角（对 review 比抽象球更直接）：
  成功案例：从 makeFillet 结果里取圆柱(fillet)面；
  失败案例：构造"本该是"的圆角面（会与几何/彼此穿插，直接显示为何失败）。
每组：两支撑面 + 共享棱 + 两面外法向箭头 + 圆角面。

凸/凹判据（穿过材料的二面角）：凸<180°(削棱,法向岔开)；凹>180°(填角,法向对冲指向缺口)。
print() 只用 ASCII（FreeCADCmd stdout）；note 的 message 是 JSON，可中文。
"""
import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import occ_capture as cap  # noqa: E402

import Part  # noqa: E402
import FreeCAD as App  # noqa: E402
V = App.Vector

SESSION = Path(os.environ.get("OCC_DEBUG_SESSION", str(REPO / ".occ-debug" / "sessions" / "cvx-demo")))
(SESSION / "assets").mkdir(parents=True, exist_ok=True)

R = 2.0
TEAL, BLUE, RED, YEL, ORANGE, REDF = "#5bc0be", "#6a9bd8", "#ff5d5d", "#ffd24a", "#e0883a", "#ff4d4d"


def emit_shape(shape, ent_id, group, label, color, opacity=0.5):
    run_id = cap._run_id(SESSION)
    rel = run_id + "/" + ent_id.replace("/", "_") + ".brep"
    p = SESSION / "assets" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    shape.exportBrep(str(p))
    bb = shape.BoundBox
    cap._append(SESSION, op="add", id=ent_id, group=group, kind="shape", label=label,
                geometry={"bbox": {"min": [bb.XMin, bb.YMin, bb.ZMin], "max": [bb.XMax, bb.YMax, bb.ZMax]}},
                asset={"format": "occt-brep", "path": rel}, style={"color": color, "opacity": opacity})


def emit_vector(o, d, ent_id, group, label, color, length=4.0):
    cap._append(SESSION, op="add", id=ent_id, group=group, kind="vector", label=label,
                geometry={"origin": list(o), "direction": list(d), "length": length}, style={"color": color})


def emit_edge(p0, p1, ent_id, group, label, color):
    cap._append(SESSION, op="add", id=ent_id, group=group, kind="polyline", label=label,
                geometry={"points": [list(p0), list(p1)]}, style={"color": color, "line_width": 8})


def note(msg):
    cap._append(SESSION, op="note", level="info", message=msg)


def find_edge(solid, x, y):
    for e in solid.Edges:
        vs = e.Vertexes
        if len(vs) == 2 and all(abs(v.X - x) < 1e-6 and abs(v.Y - y) < 1e-6 for v in vs):
            return e
    return None


def real_fillet_faces(solid, edge, r):
    """对 edge 打 r 圆角，返回结果里的圆柱(fillet)面；失败/无则 None。"""
    try:
        res = solid.makeFillet(r, [edge])
    except Exception:
        return None
    cyl = [f for f in res.Faces if isinstance(f.Surface, Part.Cylinder)]
    return cyl or None


def constructed_fillet(corner, n1, n2, sign, r, sweep):
    """构造理想滚球圆角面（一段四分之一圆柱）：成功时≈真实面，失败时='本该是'的面（会穿插）。"""
    cc = tuple(corner[i] + sign * r * (n1[i] + n2[i]) for i in range(3))   # 滚球中心线
    T1 = tuple(cc[i] - sign * r * n1[i] for i in range(3))                  # 面1 切点
    T2 = tuple(cc[i] - sign * r * n2[i] for i in range(3))                  # 面2 切点
    s = r / math.sqrt(2.0)
    Pmid = tuple(cc[i] - sign * s * (n1[i] + n2[i]) for i in range(3))      # 弧中点（凸向棱角）
    return Part.Arc(V(*T1), V(*Pmid), V(*T2)).toShape().extrude(V(*sweep))


def scene(solid, edge_xy, n1, n2, sign, group, tag, r=R):
    x, y = edge_xy
    edge = find_edge(solid, x, y)
    faces = [f for f in solid.Faces if edge and any(te.isSame(edge) for te in f.Edges)]
    for i, f in enumerate(faces[:2]):
        emit_shape(f, group + "/face%d" % (i + 1), group, tag + " support face %d" % (i + 1),
                   [TEAL, BLUE][i], 0.4)
    emit_edge((x, y, 0), (x, y, 10), group + "/edge", group, tag + " shared edge", RED)
    mid = (x, y, 5.0)
    emit_vector(mid, n1, group + "/n1", group, tag + " outward normal 1", YEL)
    emit_vector(mid, n2, group + "/n2", group, tag + " outward normal 2", YEL)
    rff = real_fillet_faces(solid, edge, r)
    if rff:
        for i, f in enumerate(rff):
            emit_shape(f, group + "/fillet%d" % i, group, tag + " REAL fillet face (r=%.1f)" % r, ORANGE, 0.9)
    else:
        cf = constructed_fillet((x, y, 0.0), n1, n2, sign, r, (0, 0, 10))
        emit_shape(cf, group + "/fillet", group, tag + " intended fillet (FAILED)", REDF, 0.7)


cap._append(SESSION, op="clear_scene", include_protected=True)   # 清场：避免跨 run 重 id 被拒

note("【凸圆角 convex】方块外棱(材料夹角90°<180°)：外法向【岔开】(背着材料)；橙色=真实圆角面，把外棱削圆。")
scene(Part.makeBox(10, 10, 10), (10.0, 0.0), (1, 0, 0), (0, -1, 0), -1, "convex", "convex")

L = Part.makeBox(5, 20, 10, V(20, 0, 0)).fuse(Part.makeBox(20, 5, 10, V(20, 0, 0)))
note("【凹圆角 concave】L形内角(材料夹角270°>180°)：外法向【对冲指向缺口】；橙色=真实圆角面，把内角填圆。")
scene(L, (25.0, 5.0), (1, 0, 0), (0, 1, 0), +1, "concave", "concave")

# ── 凹 + 大半径【失败】：窄槽宽4，左右两个'本该是'的圆角面(r=3)在槽中间重叠穿插 ──
G = "concave-fail"
chan = Part.makeBox(20, 12, 10, V(50, 0, 0)).cut(Part.makeBox(4, 14, 6, V(58, -1, 6)))
emit_shape(chan, G + "/solid", G, "slot block (width 4)", "#8a93a8", 0.18)
emit_edge((58, 0, 6), (58, 12, 6), G + "/edgeL", G, "inner bottom edge L", RED)
emit_edge((62, 0, 6), (62, 12, 6), G + "/edgeR", G, "inner bottom edge R", RED)
emit_vector((58, 6, 6), (0, 0, 1), G + "/n1", G, "floor outward normal", YEL)
emit_vector((58, 6, 6), (1, 0, 0), G + "/n2", G, "left-wall outward normal", YEL)
fL = constructed_fillet((58, 0, 6), (0, 0, 1), (1, 0, 0), +1, 3.0, (0, 12, 0))
fR = constructed_fillet((62, 0, 6), (0, 0, 1), (-1, 0, 0), +1, 3.0, (0, 12, 0))
emit_shape(fL, G + "/filletL", G, "intended fillet @left (r=3)", REDF, 0.6)
emit_shape(fR, G + "/filletR", G, "intended fillet @right (r=3)", ORANGE, 0.6)
note("【凹+大半径 失败】窄槽宽4：左右两个'本该是'的圆角面(红/橙,r=3)在槽中间重叠穿插→"
     "两个圆角塞不进同一条槽→makeFillet 抛 StdFail_NotDone。同槽 r≤2 不重叠则能成。")

note("看圆角面：橙=能成的真实圆角 / 红=失败(穿插)；外法向：岔开=凸(削棱) / 对冲指向缺口=凹(填角)。")
print("[cvx-concave] convex + concave-ok + concave-fail (fillet surfaces, no ball)")
