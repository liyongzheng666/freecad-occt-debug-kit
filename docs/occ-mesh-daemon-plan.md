# occ-mesh-daemon — 实现交接文档（M2-3）

> 状态：**设计已锁定，未实现**。本文件是**给新窗口/新 agent 自包含开干用的规格**，照它写代码即可，不必回读历史对话。<br>
> 用途：建一个**常驻守护进程**，watch 调试会话的 `assets/*.brep`，调用 `occ-debug-mesh` 网格化，并向 `events.ndjson` 追加 `update`/`defect` 事件，让 Print viewer 把占位升级成真三角网格。<br>
> 上游设计（真源，按需查，不必全读）：
> [m2-research-notes.md](m2-research-notes.md)（§2.3 / §3 已锁方案、§6 文件清单、风险表 V1/V6/V8/N4/N6/N7）、
> [print-linkage-tech-decisions.md](print-linkage-tech-decisions.md)（§1 接缝、§3 硬契约）、
> 协议真源 [tools/Print/protocol/event.schema.json](../tools/Print/protocol/event.schema.json)、
> 工具 [tools/occ-debug-mesh/README.md](../tools/occ-debug-mesh/README.md)。

---

## 1. 在系统里的位置（已锁定，2026-06-22 敲定）

三方组合：**M2-1 = A 异步 renderer + 占位替换；M2-2 = B 两段式 add→update；M2-3 = A 独立守护进程 watch assets/**。

```text
occdbg(断点内) ──写 *.brep 到 assets/──┐
   └─发 add(kind:shape, 占位 bbox + occt-brep 资产引用)──► <session>/events.ndjson
                                                            ▲
occ-mesh-daemon (本文件要建) ── watch assets/*.brep ────────┤
   ├─ occ-debug-mesh: *.brep → *.mesh.json (+ .geom.json / .defects.json)
   ├─ 算 .mesh.json 的 sha256              ← 顺手实现 V7
   └─ flock 原子追加 update(资产换 print-mesh) + 每条 defect 事件
                                                            │
viewer ── add 时画占位 bbox ──收到 update──► fetch /assets/<mesh> ──► 替换为真三角网格
```

**边界（硬约束）**：daemon 属 **kit 生产端**，与被调试进程**完全解耦**（不在冻住的断点里 shell out）。Bridge 只静态托管 `assets/`、tail `events.ndjson`，**永不调用 kit 二进制**。

**唯一共享**：Session 目录 `<session>/`（`events.ndjson` + `assets/`），路径经环境变量 `OCC_DEBUG_SESSION` 握手。

---

## 2. 要建/改的东西

| 文件 | 新/改 | 仓 | 内容 |
| --- | --- | --- | --- |
| `scripts/occ-mesh-daemon.py` | **新** | kit | 核心守护进程（见 §3/§4/§5） |
| `scripts/occ-debug-start.sh` | 新（S4） | kit | F5 编排 + 就绪顺序 + daemon 生命周期（N7） |
| `scripts/fake-occ-session.py` | 改 | kit | 扩一个「发 shape+occt-brep 资产 add + 投放 .brep」的离线驱动（§6 测试用） |
| `viewer/src/rendering/renderers/basicRenderers.ts` | 改（S2） | **Print** | 注册 `shape`/`face`/`surface_patch` mesh renderer + 异步占位替换（M2-1 A） |
| `viewer/src/rendering/SceneController.ts` | 改（S2） | Print | 资产 `print-mesh` 到达后 fetch `/assets/<path>` 建三角 mesh，替换占位 |

> kit 侧改动走 kit 仓（`liyongzheng666/freecad-occt-debug-kit`），分支→PR→合并 main。
> Print 侧改动走 Print 仓（`liyongzheng666/Print`），同样分支→PR。两仓分开提交。

---

## 3. daemon 行为规格（`occ-mesh-daemon.py`）

Python 标准库，**零第三方依赖**（与 Bridge 同栈，不与 FreeCAD pixi Python 冲突）。

**CLI**：
```
occ-mesh-daemon.py [--session DIR] [--interval 0.2] [--once]
  --session  缺省读 $OCC_DEBUG_SESSION，再缺省 .occ-debug/sessions/dev
  mesher 二进制 = $OCC_DEBUG_MESH_BIN，缺省 tools/occ-debug-mesh/build/occ-debug-mesh   (风险 V8)
  --once     扫一轮就退出（测试用）；否则常驻轮询
```

**轮询循环**（每 `--interval` 秒，默认 0.2s；stdlib 无 inotify/FSEvents，**轮询 tail**，与 Bridge 一致）：

```
1. 增量读 events.ndjson 新行 → 维护映射 brep2id = { asset.path(.brep) : entity_id }
   只认 op=="add" 且 asset.format=="occt-brep" 的事件；记住已读到的字节偏移。
2. 扫 assets/**/*.brep：对每个「在 brep2id 里有 id、且尚未网格化」的 brep：
     a. out = <brep 去掉 .brep>.mesh.json
     b. 调 occ-debug-mesh：subprocess [MESHER, brep, out]，超时（如 30s，对应 V2 层2）
     c. 读 out 算 sha256（hashlib，64 hex）
     d. flock 原子追加一条 update 事件（§4）
     e. 读 <base>.defects.json，每条 defect 追加一条 defect 事件（§4）
     f. 失败路径见 §5（N6）
3. 幂等：out 已存在 或 已在 emitted 集合里 → 跳过（避免重复网格化/重复 update）。
```

**brep → entity id 关联（关键决策）**：daemon **读 events.ndjson** 找到引用该 brep 的 add 事件，取其 `id`。理由：`asset.path` 是 add 事件里就有的现成关联，无需额外命名约定；daemon 本就要 tail 这个文件。若一个 brep 落地时其 add 还没出现，**下一轮再处理**（保持映射、轮询补上）。

**run_id / seq 命名空间（风险 V1，必须这么做）**：daemon 自己产生的所有事件用**独立 run_id `<原run>/mesh`**（如 `run-0001/mesh`），自己维护这个 run 的 `seq` 自增。`update` 靠**全局 `id`** 命中原实体（跨 run 生效）；reducer 按 run 各自跟 `lastSeqByRun`，所以三家写同一文件也不会 seq 撞车。

---

## 4. 事件形状（严格对 [event.schema.json](../tools/Print/protocol/event.schema.json)）

所有事件含公共头：`schema_version:"1.0"`, `session_id`, `run_id`, `seq`, `op`（+可选 `timestamp_ns`）。

**occdbg 先发的占位 add**（daemon **不产**，仅说明输入；离线由 fake-occ-session 产）：
```jsonc
{ "schema_version":"1.0", "session_id":"…", "run_id":"run-0001", "seq":7,
  "op":"add", "id":"shape-7", "group":"debug", "kind":"shape",
  "geometry": { "bbox": { "min":[…], "max":[…] } },        // 占位：viewer 先画包围盒
  "asset": { "format":"occt-brep", "path":"run-0001/shape-7.brep" } }
```
（schema：`add` 必填 `id/group/kind`；`asset.format∈{occt-brep,print-mesh}`，`path` 相对 `<session>/assets/` 无前导 `/`。）

**daemon 追加的升级 update**：
```jsonc
{ "schema_version":"1.0", "session_id":"…", "run_id":"run-0001/mesh", "seq":1,
  "op":"update", "id":"shape-7",
  "patch": { "asset": { "format":"print-mesh",
                        "path":"run-0001/shape-7.mesh.json",
                        "sha256":"<64位hex>" } } }
```
（schema：`update` 必填 `id/patch`；`asset.sha256` 须匹配 `^[a-fA-F0-9]{64}$`。reducer 把 `patch` merge 进 id 命中的实体。）

**daemon 追加的 defect**（来自 `.defects.json`，直接透传工具产出的 `defect` 对象，补 `ref.entity_id`）：
```jsonc
{ "schema_version":"1.0", "session_id":"…", "run_id":"run-0001/mesh", "seq":2,
  "op":"add", "id":"shape-7/defect-0", "group":"defects", "kind":"defect",
  "defect": { "category":"non_manifold", "source":"topology", "severity":"error",
              "status":"NonManifoldEdge", "ref":{ "entity_id":"shape-7", "edge_id":"E1" } } }
```

**（可选，S3+）**：像 [mesh-to-session.py](../scripts/mesh-to-session.py) 那样把 `.geom.json` 的 UV 折成 `metadata.uv`，并进 update 的 `patch.metadata`，点亮 P0b UV 面板。

**写入纪律（风险 N4 + 接缝 §3.4）**：整行 JSON **一次 `write()` 带 `\n`**；append 前 `fcntl.flock(LOCK_EX)`（多写者字节交错防护）。事件行保持短——大数据走 `asset` 引用，已是。

---

## 5. 硬契约速查（docs 风险表已给解法）

| 级别 | 风险 | 解法（照做） |
| --- | --- | --- |
| 🔴 V1/M2-12 | 三家写 events.ndjson，同 run_id 的 seq 无单一权威 | daemon 用独立 `run-NNNN/mesh` run_id，自管 seq；update 靠全局 `id` 命中 |
| 🟠 N4 | O_APPEND 仅对 <~4KB 原子，超长行交错损坏 | 行短（资产走引用）+ `flock(LOCK_EX)` 包 append |
| 🟠 V6/M2-16 | update 到时实体已被 remove | viewer reducer 把「update 未知 id」降为低级诊断（Print 侧，已有诊断仅调级别） |
| 🟠 V8 | daemon 怎么找 mesher | `OCC_DEBUG_MESH_BIN`，缺省 `tools/occ-debug-mesh/build/occ-debug-mesh` |
| 🟠 N6 | 网格化失败发什么 | 工具 `partial=true` → update 照发（带部分网格），并补 defect；进程失败/超时 → 发 `note(level:"capture_failure", message:…)`，**保留占位**、不发 update |
| 🟡 N7 | daemon 生命周期 | `occ-debug-start.sh`（S4）记 PID、健康检查、崩溃可见 |

---

## 6. 离线测试路径（**无需 LLDB / FreeCAD**，关键价值）

全链路可离线验证：

```bash
S=.occ-debug/sessions/dev
BIN=tools/occ-debug-mesh/build/occ-debug-mesh

# 0. 工具就绪
scripts/build-occ-debug-mesh.sh

# 1. 造个真 BREP 投进 assets/，并由 fake-occ-session 发对应的占位 add
$BIN --make-test-nonmanifold "$S/assets/run-0001/shape-7.brep"
scripts/fake-occ-session.py --session "$S" --emit-shape-asset run-0001/shape-7.brep   # ← 本次要扩的入口

# 2. 起 daemon：网格化 + 追加 update + defect
scripts/occ-mesh-daemon.py --session "$S" --once     # --once 跑一轮便于断言

# 3. 断言（新写个小脚本或并进 fake/daemon 自检）：
#    - events.ndjson 出现 run_id=="run-0001/mesh" 的 update(id=shape-7, patch.asset.format=print-mesh)
#    - 该 asset.sha256 == sha256(assets/run-0001/shape-7.mesh.json)
#    - 出现 kind=="defect" 的事件，ref.entity_id=="shape-7"
#    - 所有事件过 event.schema.json 校验（用 jsonschema，见 scripts/validate-events.py 计划）

# 4. 真看（可选）：起 Bridge + viewer
tools/Print/bridge/bridge.py --session "$S" --port 7341
( cd tools/Print && npm run dev )    # 占位 bbox → 秒级换成三角网格（需 S2 的 renderer）
```

---

## 7. 切片与验收（建议按序）

| 切片 | 范围（仓） | 验收 |
| --- | --- | --- |
| **S1 daemon 最小闭环** | kit：`occ-mesh-daemon.py`（watch→mesh→sha256→flock 追加 update）+ 扩 `fake-occ-session` + 断言脚本。**先不发 defect** | 离线断言：events.ndjson 出现 `run-NNNN/mesh` 的 update、sha256 对得上、过 schema 校验 |
| **S2 viewer 三角渲染** | Print：basicRenderers 注册 shape/face mesh renderer + SceneController 异步占位替换（复用 P0b `MeshGeometry`） | viewer 实显占位 bbox → 三角网格；`tsc` + vitest 绿 |
| **S3 defect + 失败路径** | kit：追加 defect 事件 + N6 partial/全败处理；（可选）metadata.uv | 离线断言：defect 事件出现、失败发 note 不发 update |
| **S4 编排 + 生命周期** | kit：`occ-debug-start.sh`（建 session→起 daemon→baseline→lldb）+ N7 PID/健康 | F5 一键起；daemon 崩溃可见可重启 |

**S1 是关键路径**：纯 kit 侧 Python、可完全离线断言、不碰 LLDB/Print，风险最低、最快见效。S2 在 Print 仓单独做。

---

## 8. 接手须知（避免踩坑）

- **不要 truncate `events.ndjson`**（接缝 §3.2）：Bridge tail + 冷启动回放依赖追加语义；reset 是追加 `clear_scene` 不是物理截断（见 `fake-occ-session.py` 头部注释）。
- **daemon 只追加、不改写**已有行；SSE 的 `id` 由 Bridge 按行号/字节偏移分配，daemon 不管（只管协议 `run_id`/`seq`）。
- **资产路径**：`asset.path` 相对 `<session>/assets/`、无前导 `/`，映射到 Bridge `/assets/<path>`。
- **工具输出**：`occ-debug-mesh in.brep out.mesh.json` 会**同时**写 `out.geom.json` 与 `<base>.defects.json`（`<base>` = 去掉 `.mesh.json`）。
- **幂等**：daemon 重启后不能重复网格化/重复发 update——靠「`.mesh.json` 已存在」+ 内存 emitted 集合双保险。
- kit 改动走 kit 仓分支→PR；Print 改动走 Print 仓分支→PR；**两仓分别提交**。
