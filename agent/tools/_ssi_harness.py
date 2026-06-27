"""FreeCAD 侧 SSI 探针 harness —— 在 FreeCADCmd 进程内运行（**不是 agent 包的一部分**）。

由 ssi_probe.py 通过环境变量驱动（同 _fillet_harness：FreeCADCmd 把位置参当文档打开）：
  SSI_FIXTURE     内置面对 id（"transversal" / "near-tangent" / "tangent" / "secant"）
  SSI_FACE_A/B    或直接给两个 BREP 面文件路径（优先于 fixture）
  SSI_TANGENT_EPS 近切阈值（度，默认 5）
  SSI_OUT_JSON    SSIReport JSON 输出路径

脱离 ChFi3d 单独跑面面求交（intersectSS = 无界曲面交；section = 有界面拓扑接触），
配 distToShape + Surface.normal 量近切角。结果写 JSON（不 print，免 stdout ASCII 坑）。
"""
import json
import math
import os

import FreeCAD as App
import Part

V = App.Vector


def _cyl_lateral(solid):
    for f in solid.Faces:
        if isinstance(f.Surface, Part.Cylinder):
            return f
    return solid.Faces[0]


def _rect_face_x(x, ys, zs):
    """x=const 平面上的显式矩形面（精确摆位，避免 makePlane 隐式 u/v 朝向坑）。"""
    pts = [V(x, ys[0], zs[0]), V(x, ys[1], zs[0]), V(x, ys[1], zs[1]), V(x, ys[0], zs[1])]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def fixture(name):
    if name == "transversal":                                  # 两平面 90 度横切
        fa = Part.makePlane(20, 20, V(-10, -10, 0), V(0, 0, 1))   # XY
        fb = Part.makePlane(20, 20, V(-10, 0, -10), V(0, 1, 0))   # XZ，沿 x 轴相交
        return fa, fb
    cyl = _cyl_lateral(Part.makeCylinder(10, 20))              # 轴 z，r=10，侧面（blend 面代理）
    # 矩形跨 y=0（圆柱最近点 (10,0,z) 处），保证 distToShape 落在真正的最近接触区
    if name == "secant":                                       # 平面穿过圆柱（x=5）
        return cyl, _rect_face_x(5.0, (-12, 12), (2, 18))
    if name == "tangent":                                      # 平面恰切（x=10）
        return cyl, _rect_face_x(10.0, (-3, 3), (2, 18))
    if name == "near-tangent":                                 # 平面紧贴但离开（x=10.1）→ 期望接触却 0
        return cyl, _rect_face_x(10.1, (-3, 3), (2, 18))
    raise ValueError("unknown SSI fixture: " + str(name))


def load_face(path):
    s = Part.Shape()
    s.read(path)
    return s.Faces[0] if s.Faces else s


def normal_at(face, pt):
    u, v = face.Surface.parameter(pt)
    n = face.Surface.normal(u, v)
    return n


def dihedral_and_gap(fa, fb):
    """两面最近点处的法线夹角(度) + 最近距离。"""
    d = fa.distToShape(fb)
    gap = float(d[0])
    pa, pb = d[1][0]
    na, nb = normal_at(fa, pa), normal_at(fb, pb)
    cosang = abs(na.dot(nb)) / (na.Length * nb.Length)
    ang = math.degrees(math.acos(min(1.0, max(-1.0, cosang))))
    return round(ang, 4), round(gap, 6)


def main():
    out_json = os.environ["SSI_OUT_JSON"]
    eps = float(os.environ.get("SSI_TANGENT_EPS", "5"))
    result = {"error": None}
    try:
        a, b = os.environ.get("SSI_FACE_A"), os.environ.get("SSI_FACE_B")
        if a and b:
            fa, fb = load_face(a), load_face(b)
        else:
            fa, fb = fixture(os.environ.get("SSI_FIXTURE", "near-tangent"))

        n_ss = len(fa.Surface.intersectSS(fb.Surface))
        n_sec = len(fa.section(fb).Edges)
        ang, gap = dihedral_and_gap(fa, fb)

        near_tangent = ang < eps
        degenerate = n_sec == 0
        result.update(
            n_curves_ss=n_ss,
            n_section_edges=n_sec,
            min_dihedral_deg=ang,
            gap=gap,
            near_tangent=near_tangent,
            degenerate_contact=degenerate,
            s3_signature=bool(near_tangent and degenerate),
        )
    except Exception as e:
        import traceback
        result["error"] = type(e).__name__ + ": " + str(e)
        result["traceback"] = traceback.format_exc()

    with open(out_json, "w") as fp:
        json.dump(result, fp, ensure_ascii=False)


main()
