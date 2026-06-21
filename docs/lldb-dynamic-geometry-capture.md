# LLDB 动态几何采集设计

> 状态：已接受的架构决策<br>
> 适用范围：FreeCAD / OCCT Debug 构建、Print Session 协议<br>
> 核心目标：在断点暂停时任意输出当前点、曲线、拓扑和 Shape，无需为每次观察修改源码或重新编译

## 1. 决策摘要

几何采集采用三种互补模式，优先级如下：

1. **LLDB 动态命令**：人类开发者在任意安全断点查看当前变量，默认优先。
2. **断点自动命令**：将采集动作挂到断点后自动继续，适合 Agent 和重复观察。
3. **源码埋点**：仅用于高频循环、极短生命周期、异常前关键状态和无人值守标准诊断。

三种模式共享同一个 `OccDebugCapture`、Session 目录和 Print 协议。Print 不区分事件来自 LLDB、断点命令还是源码宏。

该决策不等价于让 Agent 在 MVP 中通过 DAP 自动驾驶调试器。第一阶段的采集能力仍由 LLDB Python 命令和 LLDB batch script 完成；但第一版允许 Kit 的轻量 VS Code 扩展使用公开 DAP 请求，把 Variables/Watch 右键操作路由到指定 frame 的同一条 LLDB 命令。Agent 的高层 DAP 控制仍属于后续范围。

## 2. 使用体验

FreeCAD/OCCT 在断点暂停后：

```text
Variables / Watch 右键
  └─ 发送到 Print（自动识别）
     发送到 Print：Point / Curve / Edge / Wire / Face / Shape
```

高级用户也可以在 Debug Console 直接执行：

```text
(lldb) occdbg session
(lldb) occdbg group fillet/stripe/2

(lldb) occdbg point P1 -- CP.Point()
(lldb) occdbg point2d uv1 -- SD->Get2dPoints(true, 1)
(lldb) occdbg curve intersection -- C3d First Last
(lldb) occdbg edge selected-edge -- edge
(lldb) occdbg face support-face -- HS1->Face()
(lldb) occdbg shape input-shape -- myShape
(lldb) occdbg surfdata current-sd -- SD

(lldb) occdbg clear fillet/stripe/2
(lldb) occdbg focus P1
```

`--` 后面的内容原样作为当前栈帧中的 C++ 表达式。调用完成后，Bridge 读取 Session，Print 增量显示对应对象。

### 2.1 命令反馈

成功：

```text
[occdbg] add point fillet/stripe/2/P1 seq=37
```

变量不可见：

```text
[occdbg] expression failed: use of undeclared identifier 'CP'
```

Handle 为空：

```text
[occdbg] skipped current-sd: null ChFiDS_SurfData handle
```

Capture 不可用：

```text
[occdbg] libOccDebugCapture is not loaded; run `occdbg load`
```

### 2.2 VS Code 右键发送

右键入口是第一版 P0 能力，不是后续增强。Kit 内的工作区扩展从 Variables 使用 `evaluateName`、从 Watch 使用原始表达式，恢复变量所属 `frameId/threadId/frameIndex` 后调用统一的 `occdbg emit`。格式化后的 `value` 只能显示，不能作为表达式执行。

扩展通过 Base64 JSON 请求传递表达式、kind、label 和 group，避免 C++ 模板、引号和空格的命令行转义问题。自动类型识别存在歧义时必须让用户选择类型；多线程或递归调用中无法确认 frame 时必须拒绝静默猜测。完整设计见 [VS Code 一键发送几何到 Print](vscode-send-to-print.md)。

## 3. 组件结构

```text
tools/vscode-occ-debug
        │ Variables/Watch + exact frameId
        ▼
scripts/lldb_occ_debug.py
        │
        ├── 简单值：SBValue 读取 → Python 写 NDJSON
        │
        └── 复杂几何：调用目标进程中的 C ABI
                         │
                         ▼
              libOccDebugCapture.dylib
                         │
                NDJSON + BREP assets
                         │
                         ▼
                   Print Bridge
```

目录建议：

```text
freecad-occt-debug-kit/
├── tools/vscode-occ-debug/
│   ├── package.json
│   ├── src/
│   └── test/
├── tools/occ-debug-capture/
│   ├── CMakeLists.txt
│   ├── include/
│   │   ├── OccDebugCApi.h
│   │   ├── OccDebugSession.hxx
│   │   └── OccDebugExport.hxx
│   └── src/
│       ├── CApi.cxx
│       ├── SessionWriter.cxx
│       ├── ExportCurve.cxx
│       └── ExportTopology.cxx
├── scripts/
│   ├── lldb_occ_debug.py
│   └── lldb_occ_debug_commands.py
└── tests/occ-debug-capture/
```

## 4. Capture 动态库

动态库提供稳定 C ABI，避免 LLDB 处理 C++ 名字修饰和重载：

```cpp
extern "C" {

int OccDebug_EmitPoint(
    const char* group,
    const char* id,
    const gp_Pnt* point,
    const char* sourceFile,
    int sourceLine,
    const char* sourceFunction);

int OccDebug_EmitCurve(
    const char* group,
    const char* id,
    const Handle(Geom_Curve)* curve,
    double first,
    double last);

int OccDebug_EmitShape(
    const char* group,
    const char* id,
    const TopoDS_Shape* shape);

int OccDebug_ClearGroup(const char* group);

const char* OccDebug_LastError();

}
```

返回值约定：

- `0`：成功。
- 正数：可恢复的跳过，如空 Shape、空 Handle。
- 负数：Capture 内部失败；错误文本通过 `OccDebug_LastError()` 获取。

任何错误都不能向 OCCT 抛异常。

### 4.1 为什么需要一次性动态库

LLDB Python 可以读取简单字段，但不能可靠地在调试器进程内重新实现：

- `BRepTools::Write()`。
- `BRepAdaptor_Curve` 和自适应离散。
- Face/Wire/Edge occurrence 遍历。
- Pcurve 读取。
- OCCT Handle 和容器语义。

这些操作必须由与目标进程使用相同 OCCT ABI 的 C++ 库完成。

动态库只在 API 或实现变化后重新编译；观察不同变量不需要重新编译 FreeCAD、OCCT 或 Capture。

## 5. LLDB Python 命令插件

`scripts/lldb_occ_debug.py` 通过 `command script import` 注册 `occdbg` 命令族。

插件职责：

1. 解析子命令、ID、group 和 `--` 后的表达式。
2. 获取当前 process、thread、frame。
3. 检查进程是否暂停、栈帧是否有效。
4. 计算表达式并输出清晰错误。
5. 简单类型直接序列化，复杂类型调用 C ABI。
6. 将当前源码位置、函数和 frame 信息附加到事件。
7. 不在 Python 中持有目标对象地址超过当前暂停周期。

### 5.1 简单类型路径

以下类型优先通过 `lldb.SBValue` 读取，不执行目标函数：

- `gp_Pnt`、`gp_Pnt2d`。
- `gp_Vec`、`gp_Dir`。
- 标准整数、浮点数和枚举。
- 可安全枚举的小型基础数组。

流程：

```text
frame.EvaluateExpression(expr)
        ↓
SBValue + OCCT formatter helpers
        ↓
Python SessionWriter
        ↓
NDJSON
```

### 5.2 复杂类型路径

以下类型调用目标进程内的 Capture C ABI：

- `TopoDS_Shape` 及其子类。
- `Handle(Geom_Curve)`、`Handle(Geom_Surface)`。
- Face、Edge、Wire 和 BREP。
- `ChFiDS_Stripe`、`ChFiDS_SurfData` 适配器。

LLDB 插件生成带声明的表达式：

```cpp
extern "C" int OccDebug_EmitShape(
    const char*, const char*, const TopoDS_Shape*);

auto __occdbg_value = (myBuilder.Shape());
OccDebug_EmitShape(
    "fillet/result",
    "current-shape",
    &__occdbg_value);
```

使用局部临时值可以支持 `builder.Shape()` 等返回值表达式，而不要求源码中预先存在命名变量。

## 6. 动态库加载

推荐由 LLDB 显式加载：

```text
(lldb) process load /absolute/path/libOccDebugCapture.dylib
```

封装为：

```text
(lldb) occdbg load
```

插件从工作区配置或环境变量读取路径：

```bash
OCC_DEBUG_CAPTURE_LIB=/path/to/libOccDebugCapture.dylib
OCC_DEBUG_SESSION=/path/to/session
OCC_DEBUG_RUN_ID=run-0001
```

备选方式是启动前设置 `DYLD_INSERT_LIBRARIES`，但显式 `process load` 更容易报告失败和核对加载版本。

CodeLLDB 的 launch profile 继续导入：

```json
{
  "initCommands": [
    "command script import ${workspaceFolder}/scripts/lldb_occt_formatters.py",
    "command script import ${workspaceFolder}/scripts/lldb_occ_debug.py"
  ]
}
```

## 7. 断点自动采集

动态命令可以挂到普通 LLDB breakpoint：

```text
breakpoint set --name ChFi3d_Builder::PerformIntersectionAtEnd
breakpoint command add <breakpoint-id>
> script occdbg.capture_shape("bad-candidate", "myShape")
> continue
```

Kit 应进一步提供声明式配置：

```yaml
breakpoints:
  - function: ChFi3d_Builder::PerformIntersectionAtEnd
    actions:
      - type: point
        id: common-point
        expression: CP.Point()
      - type: shape
        id: current-shape
        expression: myShape
    continue: true
```

Runner 将配置转换为 LLDB batch commands。这样 Agent 可以自动观察标准位置，但仍不必修改 OCCT 源码。

## 8. 与源码埋点的关系

| 场景 | 动态命令 | 断点自动命令 | 源码埋点 |
| --- | --- | --- | --- |
| 临时查看一个 Shape | 首选 | 可用 | 不推荐 |
| 人工探索未知问题 | 首选 | 可用 | 不推荐 |
| 同一断点重复采集 | 可用 | 首选 | 可用 |
| 高频求解循环 | 不推荐 | 谨慎 | 首选 |
| 异常抛出前瞬间 | 可能来不及 | 可用 | 首选 |
| 无人值守标准诊断 | 可用 | 首选 | 首选 |
| 调试器表达式不安全 | 不可用 | 不可用 | 首选 |

源码宏与动态命令必须调用同一个 Capture Core：

```cpp
OCCDBG_POINT("P1", point);
```

它是稳定诊断路径，不是人类查看任意变量的唯一方式。

## 9. Fillet Adapter 和链接边界

`OccDebugCapture Core` 只能依赖低层 OCCT toolkit，例如 TKernel、TKMath、TKG2d、TKG3d、TKBRep 和 TKMesh。

它不能依赖 TKFillet，否则会形成：

```text
TKFillet → OccDebugCapture → TKFillet
```

因此 `ChFiDS_Stripe`、`ChFiDS_SurfData` 的解释器放在 TKFillet 内部适配层中，再调用通用 Capture API。动态命令 `occdbg surfdata` 可以调用由 TKFillet 暴露或调试构建注入的专用 C ABI。

## 10. 安全限制

“任意调用”指在任意**安全暂停点**调用当前栈帧可见表达式，不代表在任意进程状态都安全。

禁止或谨慎使用：

- 进程仍在运行。
- 信号处理器、内存分配器或动态链接器内部。
- 进程堆已经严重损坏。
- 当前线程持有 Capture 也要获取的锁。
- 异常展开或析构链中的敏感位置。
- 表达式会产生明显算法副作用。

LLDB 目标函数调用会短暂恢复目标线程并执行代码，可能分配内存。对于简单 `gp_Pnt` 应优先使用 SBValue 路径。

变量还必须满足：

- 位于当前或可切换到的有效栈帧。
- 未被编译器优化掉。
- Handle/指针有效。
- 临时对象在调用完成前保持生命周期。

## 11. Session 和序号

动态命令继续写标准 Print 事件：

```json
{
  "schema_version": "1.0",
  "session_id": "20260621-203015",
  "run_id": "run-0001",
  "seq": 37,
  "op": "add",
  "id": "fillet/stripe/2/P1",
  "group": "fillet/stripe/2",
  "kind": "point",
  "metadata": {
    "producer": "lldb-dynamic"
  }
}
```

`metadata.producer` 可取：

- `lldb-dynamic`
- `lldb-breakpoint`
- `source-probe`
- `freecad-baseline`

Print 只将该字段用于诊断和筛选，不改变渲染逻辑。

## 12. 第一阶段实施顺序

1. `SessionWriter` 和事件写入测试。
2. `libOccDebugCapture.dylib` 最小 C ABI。
3. `lldb_occ_debug.py` 的 `session/group/point/clear`。
4. `occdbg shape` 和 BREP 原子写入。
5. `occdbg curve/edge/face`。
6. Print Bridge tail NDJSON。
7. VS Code Variables/Watch 发送扩展、DAP frame 映射和 F5 编排。
8. 断点自动采集和 LLDB batch runner。
9. Fillet 的 Stripe/SurfData 动态适配器。
10. 只为关键、高频路径增加源码宏。

## 13. 验收标准

- Capture 动态库只需构建和加载一次。
- 在任意有效断点可输出当前 `gp_Pnt`，无需修改源码。
- 可输出当前 `TopoDS_Shape` 为 BREP，并在 Print 中显示。
- 支持 `builder.Shape()` 等返回值表达式。
- Variables 和 Watch 都能右键发送到 Print，并提供自动类型和显式类型入口。
- 递归 frame、多线程和同名变量不会静默输出错误 frame 中的对象。
- 正常 F5 自动准备 Session、Bridge、Print、Capture 和 LLDB 插件。
- 表达式错误、空 Handle 和未加载动态库有明确反馈。
- 将命令挂到断点后可自动采集并继续。
- Viewer/Bridge 未启动时动态命令仍能写入 Session。
- Capture 失败不会改变圆角算法异常和返回值。
- 源码宏、动态命令和断点命令产生相同协议版本的事件。

## 14. 最终结论

人类开发者调研未知几何问题时，应优先使用 Variables/Watch 右键入口，Debug Console 的 LLDB 动态命令作为高级入口；Agent 对已知位置进行重复观察时，应以断点自动命令为主；只有高频、极短生命周期和关键失败路径才使用源码埋点。

这使 Print 成为统一的几何观察面，而不是强迫每次观察都经历“改代码—编译—运行”的工具。
