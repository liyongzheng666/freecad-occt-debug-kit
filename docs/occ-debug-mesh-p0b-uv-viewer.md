# P0b —— geom sidecar 接进交互 viewer（3D→2D 打通）

> 状态：**已完成**<br>
> 目的：把 [P0a](occ-debug-mesh-p0a-geom-sidecar.md) 导出的 geom 数据喂进 M1 交互 viewer——
> 选中面/边在 **UV 参数空间面板**画出 pcurve、Inspector 显示类型/容差/标志，全在一个能转能缩放的 3D 场景里。<br>
> 上游：[occ-debug-mesh-export-design.md](occ-debug-mesh-export-design.md)（§8 切片）、
> [uv-parametric-space-mapping.md](uv-parametric-space-mapping.md)。

## 1. 目标与范围

- `mesh-to-session.py` 读 geom sidecar → 面/边实体 metadata 注入 **UV pcurve** + 类型/容差/标志。
- `UvPanel` 从桩改成**真画参数空间 pcurve**；`Inspector` 显示几何字段。
- 复用 viewer 现有渲染（无新 renderer）。

## 2. 数据流

```
occ-debug-mesh -> <base>.geom.json
   -> mesh-to-session.py (读 geom，按 face_id/edge_id 关联) -> 实体 metadata.uv / metadata.{surface_type,curve_type,tolerance,...}
   -> Bridge SSE -> viewer：UvPanel 画 pcurve / Inspector 列字段
```

- 面实体 `metadata.uv = { panels:[{face_id, surface_type, bounds, curves:[{label,is_seam,degenerate,selected,points}]}] }`。
- 边实体：**每个承载面一个 panel**（见 §4 闭合边修复）。
- `metadata` 还塞 `surface_type`/`curve_type`/`tolerance`/`periodic`/`degenerate`/`closed`（Inspector「元数据」自动显示；大的 `uv` 被 Inspector 过滤掉）。

## 3. viewer 实现（Print 子仓）

- `features/uv-viewer/UvPanel.tsx`：桩 → 读 `metadata.uv.panels`，每面一张 SVG 小图：
  uv_bounds 矩形 + pcurve 折线（**缝红 / 极点橙虚线 / 选中白 / 普通青**），V 朝上，U/V 各向独立缩放（参数空间不强行正方形）。
- `features/inspector/Inspector.tsx`：`元数据` 段过滤掉大 `uv` 对象，其余几何字段照常显示。
- `point_set`/`polyline` 等渲染器**未改**——P0b 只加 UV 2D 绘制。

## 4. 配套修复（都属 P0b）

| # | 问题 | 修法 |
| --- | --- | --- |
| 1 | UV 面板不跟 3D 选择刷新 | `UvPanel` 改**单一组合选择器**（`selectedId` 或 `entities` 变即重算） |
| 2 | 换形状要手动刷新 | `mesh-to-session` reset 改 **`clear_scene + 新 run` 追加**（不 truncate），连着的 viewer 自动 swap；`--fresh` 才 truncate |
| 3 | 只有「显示全部」 | 加 `隐藏全部` 按钮 + store `hideAllGroups` |
| 4 | **闭合边 UV 乱**（致命）| 一条边在不同面是**不同参数空间**（圆柱 θ/h vs 平面 x/y），旧 UvPanel 混在一张图叠错。改成**按面分图（per-face panels）** + 选中边高亮白 |
| 5 | 锁定只有 bbox 能锁 | `isGroupLocked` + store `lockedGroups`/`setGroupLocked`；锁定徽章 → **任意分组 🔒/🔓 切换**；`清空调试对象` 保留锁定分组，锁定组无行内「清空」 |

## 5. 坑

- **zustand HMR**：改了 `store.ts`（如加 `hideAllGroups`/`lockedGroups`）会让 Vite 热替换重置 store 状态 → 场景变空。**数据没丢**，刷新/新标签页全量 replay 即回。改纯组件（UvPanel 等）则 fast-refresh、不清空。
- **闭合边 = 跨面**：闭合圆边总同属曲面 + 端盖，必须分图。
- 边的 UV 采样目前用 pcurve 独立离散；与 3D 折线逐点对齐（UVNode）是后续优化。

## 6. 改动文件

| 仓库 | 文件 | 改动 |
| --- | --- | --- |
| 父仓 freecad | `scripts/mesh-to-session.py` | 读 geom → metadata 注入 UV panels + 类型/容差；reset 语义；`--fresh` |
| Print 子仓 | `features/uv-viewer/UvPanel.tsx` | 桩 → 真画 per-face pcurve |
| Print 子仓 | `features/inspector/Inspector.tsx` | 过滤大 `uv`、显示几何字段 |
| Print 子仓 | `features/layers/LayerTree.tsx` | 隐藏全部 + 锁定可切换 |
| Print 子仓 | `core/scene-store/store.ts` + `reducer.ts` | `hideAllGroups`、`lockedGroups`/`setGroupLocked`、`isGroupLocked`、清空保留锁定 |
| Print 子仓 | `styles.css` | UV panels / lock-toggle 样式 |

## 7. 复现

```bash
# viewer：tools/Print 下 npm run dev（:5777/5778）；bridge：bridge/bridge.py --port 7341
python3 scripts/mesh-to-session.py /tmp/cylinder.mesh.json /tmp/sphere.mesh.json --session .occ-debug/sessions/dev
# 浏览器 viewer：点面/边 -> Inspector 看 surface_type/容差；点「UV 开启」-> 底部画 pcurve
```
