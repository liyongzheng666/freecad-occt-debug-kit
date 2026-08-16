# 圆角可视化显示约束（以本 demo 为范例固化）

本文件把 `convex_concave` demo 的显示规则**固化为约束**：以后凡用 Print viewer 展示圆角（凸/凹、成功/失败）的几何，**必须**按本表的 kind / 颜色 / 含义来发事件，确保 review 的人一眼读懂、跨 demo 一致。范例实现见 `emit.py`，效果见四个场景。

## 1. 实体类型 → kind / 颜色 / 样式 / 含义（MUST）

| 元素 | `kind` | 颜色 | 样式 | 含义 |
| --- | --- | --- | --- | --- |
| 两支撑面 | `shape` | 青 `#5bc0be` / 蓝 `#6a9bd8` | opacity 0.4 | 圆角所在的两张面（face1/face2） |
| 共享棱 | `polyline` | 红 `#ff5d5d` | line_width 8 | 被倒圆角的棱（直棱两点；圆棱采样成闭合环） |
| 外法向 ×2 | `vector` | 黄 `#ffd24a` | length 4 | 两支撑面的外法向（origin=棱上一点） |
| 真实圆角面 | `shape` | 橙 `#e0883a` | opacity 0.9 | `makeFillet` **成功**产出的圆角面（圆柱/环面） |
| 重叠/构造圆角面 | `shape` | 红 `#ff4d4d` + 橙 | opacity 0.6 | 算法放弃（可裁剪）时"本该是"的两张面（会穿插） |
| 滚球 | `point` | 红 `#ff4d4d`，`size`=r | opacity 0.5 | **仅几何真·不可能**用：球比可用空间大、塞不进 |

> 颜色固定，不得随意改。橙=能成 / 红=失败，是贯穿全 demo 的语义底色。

## 2. 凸 / 凹判据（看黄箭头即可）

- **凸 convex**（材料二面角 <180°，外棱）：两外法向**岔开**（背着材料）；圆角**削棱**。
- **凹 concave**（材料二面角 >180°，内角）：两外法向**对冲指向缺口**；圆角**填角**。

## 3. 失败三态（橙/红 + 表征方式）

| 态 | 表征 | 例（demo 场景） | 反事实修法 |
| --- | --- | --- | --- |
| ① 成功 | 橙色**真实圆角面** | convex / concave-ok | — |
| ② 算法放弃·**可裁剪** | 红/橙**重叠圆角面**（穿插） | overlap-trimmable（窄槽 r=3） | **SSI 求交+互裁**（非降半径） |
| ③ 几何**真·不可能** | 红色**滚球** > 可用空间 | geom-impossible（盲孔 R=3, r=4） | **降半径 / 改输入**（裁剪无对象） |

> 这三态正是 root-cause agent 对 `StdFail_NotDone` 该给的不同结论：别默认"降半径"，先分清"可裁剪(算法)"还是"不可能(几何)"。

## 4. 场景与会话约束（MUST）

- **布局**：每组沿 +x 排列，各占一个 `group`；组名表意（`convex` / `concave` / `overlap-trimmable` / `geom-impossible`）。
- **清场**：emitter 开头发一次 `clear_scene`（`include_protected:true`），避免跨 run 复用相同 id 被 reducer 拒绝。
- **每个圆角场景必须含**：2 支撑面 + 共享棱 + 2 外法向 + 圆角表征（成功/可裁剪用面、不可能用球）。
- **每组必有一条 `note`**：写明 凸/凹、半径、失败态（①/②/③）、对应反事实修法。
- **不画球的边界**：成功与"可裁剪"一律用圆角**面**表示（对 review 更直接）；**只有**第③态用球，且球半径=r、要明显大于可用空间。

## 5. 渲染前提（否则只见占位框）

- `shape`（面/实体）走 `assets/*.brep` → `occ-mesh-daemon --once` 网格化 → `update`；demo.py 已内置。
- `vector` / `polyline` / `point` 直接渲染，不依赖网格资产。
- 几何字段：`vector`={origin,direction,length}；`polyline`={points,closed?}；`point`={position}+`style.size`。

> 协议真源：`tools/Print/protocol/event.schema.json`；渲染器：`tools/Print/viewer/src/rendering/renderers/basicRenderers.ts`。
