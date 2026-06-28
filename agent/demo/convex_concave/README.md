# 凸 / 凹圆角对照 demo（Print viewer）

把"两面之间的圆角"是**凸**还是**凹**，用三重视觉锚画进 Print 网页 viewer，方便 review 的开发人员一眼分辨；并对照一个 OCCT 会失败的案例。

## 这个 demo 的文件（都在本目录）

| 文件 | 作用 |
| --- | --- |
| `demo.py` | 编排器（系统 python3）：调 FreeCADCmd 跑 `emit.py` 产出几何事件，再 `occ-mesh-daemon --once` 网格化 |
| `emit.py` | FreeCAD 侧几何发射器（在 FreeCADCmd 内跑）：建凸/凹几何，发 face/edge/vector/真实圆角面 事件 |
| `view.sh` | 一键起 viewer：幂等网格化 + bridge(:7341) + vite viewer(:5777) |
| `README.md` | 本文件 |

**依赖（仓库既有，不在本目录）**：`scripts/occ_capture.py`（事件追加）、`scripts/occ-mesh-daemon.py`（网格化）、`tools/Print/bridge/bridge.py`（SSE 桥）、`tools/Print/`（viewer）、`FreeCAD/build/debug/bin/FreeCADCmd`、`tools/occ-debug-mesh/build/occ-debug-mesh`。

## 跑

```bash
python -m agent.demo.convex_concave.demo     # 产出 + 网格化 session(.occ-debug/sessions/cvx-demo)
agent/demo/convex_concave/view.sh            # 起 viewer
# 浏览器打开 http://127.0.0.1:5777/
```

## 三个场景（左→右）

| 位置 | 场景 | 圆角面 | 外法向 |
| --- | --- | --- | --- |
| x≈0–10 | **凸**：方块外棱 90° | 🟠 真实圆角面（makeFillet 取的圆柱面），**削棱** | **岔开**（背着材料） |
| x≈20–40 | **凹**：L 形内角 90° | 🟠 真实圆角面，**填角** | **对冲指向缺口** |
| x≈50–70 | 窄槽宽 4，r=3 | 🔴+🟠 两圆角面**重叠穿插**，OCCT 抛 `StdFail_NotDone` | 对冲（凹） |

其余：青/蓝=两支撑面、红线=共享棱、黄箭头=两面外法向。

## 凸 / 凹判据

穿过**实体材料**的二面角：
- **凸 convex** < 180°（外棱）：圆角**削掉**棱（round）；两面外法向**岔开**（背着材料/背着圆角中心）。
- **凹 concave** > 180°（内角）：圆角**填上**角（fillet）；两面外法向**对冲指向缺口**。

## ⚠️ 第三例的局限（重要，勿误读）

第三个场景标的是 **`overlap-trimmable`（重叠·可裁剪）**，不是"几何不可能"：

- 窄槽里左右两个 r=3 圆角面在中间重叠，OCCT 的 `ChFi3d_StripeEdgeInter` 检测到带 pcurve 相交，直接抛 `StdFail_NotDone: "fillets have too big radiuses"`。
- **但这只是算法放弃**：两个重叠的圆角面完全可以**面面求交（SSI）+ 互相裁剪（trim）**，得到合法结果——中间形成一条 ridge（两圆角相交的棱）。许多 blend 内核就是这么做的。
- 因此此例的**根因是"算法放弃/未做互裁"**，对应的反事实修法是 **"SSI 互裁"**，而**不是**简单的"降半径"。这恰恰是 root-cause agent 该区分的：`StdFail_NotDone` 背后到底是"几何不可能"还是"算法能力不足"。

**真正的"几何不可能 / 球塞不进"** 是 **r > 局部凹曲率半径**：例如在一个半径 ρ 的圆孔内壁打圆角，r > ρ 时滚球比孔还大，**根本不存在**有效圆角面——那才是降半径之外无解的硬失败。本 demo 暂未含此例（planar 凹角恒有解，故用窄槽演示 OCCT 的算法放弃）。需要的话可加"孔内 r>ρ"场景做真·不可能对照。

## 相关

- 失败现场的真实崩溃点（LLDB 实测）：`agent/cases/box-r5.json`（StripeEdgeInter overflow）、`agent/cases/wedge-sliver.json`（StartSol 近切）。
- 机制探针：`agent/tools/ssi_probe.py`（面面求交）、`agent/tools/capture.py`（从活失败现场抓两面）。
