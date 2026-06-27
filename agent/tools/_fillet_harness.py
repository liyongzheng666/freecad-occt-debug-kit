"""FreeCAD 侧 fillet 复现 harness —— 在 FreeCADCmd 进程内运行（**不是 agent 包的一部分**）。

由 reproduce.py 通过环境变量驱动。为什么用 env 而非 argv：FreeCADCmd 把脚本之后的位置
参数当作"要打开的文档"，会报 `File format not supported`，故参数只能走环境变量：

  REPRO_CASE      case 几何构建器 id（如 "box" / "box-flat"）
  REPRO_RADIUS    fillet 半径
  REPRO_EDGES     可选，逗号分隔的边序号（1-based，对 shape.Edges）；空=全部边
  REPRO_OUT_BREP  结果 BREP 导出路径（成功产出形状时写）
  REPRO_OUT_JSON  RunEnd JSON 输出路径（始终写）

输出 RunEnd（架构 §24 子集）：{status, exception, phase, is_done, bad_shape}。
⚠️ status 仅表"recompute 是否跑完并产出形状"，**不是几何有效性**——有效性由 check_valid
判（全项目禁用裸 IsDone()）。这样 reproduce 不偷偷依赖 check_valid，两者在 loop 里组合。
"""
import json
import os
import traceback


def build_shape(case):
    import Part
    if case == "box":
        return Part.makeBox(10, 20, 30)          # 经典盒子；最短边 10
    if case == "box-flat":
        return Part.makeBox(30, 20, 2)           # 薄板：半径稍大即 overflow
    if case == "wedge":                          # 薄楔：两支撑面近切 ~1.7°，滚球塞不进 → StartSol echec(S2 近切)
        import FreeCAD as App
        V = App.Vector
        pts = [V(0, 0, 0), V(20, 0, 0), V(20, 0, 0.6)]
        return Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 8, 0))
    raise ValueError("unknown case: " + str(case))


def select_edges(shape, spec):
    if not spec:
        return shape.Edges
    idx = [int(x) for x in spec.split(",") if x.strip()]
    return [shape.Edges[i - 1] for i in idx]     # 1-based


def phase_of(msg):
    m = msg.lower()
    if "notdone" in m or "not done" in m:
        return "fillet_notdone"                  # ChFi3d 未完成（S2 滚球容纳 / S3 求交，待 agent 细分）
    return "unknown"


def main():
    out_json = os.environ["REPRO_OUT_JSON"]
    case = os.environ.get("REPRO_CASE", "box")
    radius = float(os.environ.get("REPRO_RADIUS", "1.0"))
    out_brep = os.environ.get("REPRO_OUT_BREP") or None
    result = {"status": "failed", "exception": None, "phase": None,
              "is_done": None, "bad_shape": None}
    try:
        shape = build_shape(case)
        if radius <= 0:                           # 仅导出基础几何（S0 输入预检用），不 fillet
            result["is_done"] = None
            result["phase"] = "input_export"
            if out_brep:
                shape.exportBrep(out_brep)
                result["bad_shape"] = out_brep
            result["status"] = "ok"
        else:
            edges = select_edges(shape, os.environ.get("REPRO_EDGES", ""))
            try:
                filleted = shape.makeFillet(radius, edges)
                result["is_done"] = True
                if out_brep:
                    filleted.exportBrep(out_brep)
                    result["bad_shape"] = out_brep
                result["status"] = "ok"          # 跑完产出形状；有效性留给 check_valid
            except Exception as e:                # fillet 算法失败（典型 StdFail_NotDone）
                result["is_done"] = False
                result["exception"] = type(e).__name__ + ": " + str(e)
                result["phase"] = phase_of(str(e))
    except Exception as e:                         # harness/几何构建本身崩
        result["exception"] = "harness: " + type(e).__name__ + ": " + str(e)
        result["phase"] = "harness"
        result["traceback"] = traceback.format_exc()

    with open(out_json, "w") as fp:
        json.dump(result, fp, ensure_ascii=False)


main()
