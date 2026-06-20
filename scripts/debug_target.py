# =====================================================================
# 调试入口脚本：在 FreeCADCmd 里跑几何操作，配合断点跟踪 OCC 源码。
# 改这里的几何 / 圆角参数，就能制造你想研究的场景（尤其是失败场景）。
# 在 VS Code 里：打开本文件 → F5（选 “调试当前脚本”）即可。
# =====================================================================
import FreeCAD as App
import Part

print("== debug target ==")
print("FreeCAD:", ".".join(App.Version()[:3]), "| OCC:", getattr(Part, "OCC_VERSION", "?"))

# ---- 场景 1：正常圆角（10mm 立方体，一条边 2mm）----
box = Part.makeBox(10, 10, 10)
ok = box.makeFillet(2.0, [box.Edges[0]])
print("[OK ] 2mm fillet  valid=%s vol=%.3f" % (ok.isValid(), ok.Volume))

# ---- 场景 2：故意失败（半径过大，10mm 立方体全部边打 20mm）----
#  ← 想抓“圆角为什么失败”，就在 OCC 源码里下断点后跑到这里
try:
    bad = box.makeFillet(20.0, box.Edges)
    print("[?? ] 20mm fillet 居然成功 valid=%s" % bad.isValid())
except Exception as e:
    print("[EXP] 20mm fillet 失败:", type(e).__name__, str(e)[:80])

print("== done ==")
