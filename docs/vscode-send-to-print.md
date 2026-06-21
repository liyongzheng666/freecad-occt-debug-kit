# VS Code 一键发送几何到 Print

> 状态：已接受的第一版 P0 设计  
> 适用范围：VS Code + CodeLLDB + FreeCAD/OCCT Debug + Print  
> 核心目标：在 Variables 或 Watch 中右键一个几何变量，直接增量发送到 Print，不修改源码、不重新编译

## 1. 第一版交付结论

第一版必须完成下面这条人类调试闭环：

```text
F5 启动 FreeCAD/CodeLLDB、Session、Bridge 和 Print
        ↓
在任意安全断点暂停
        ↓
Variables / Watch 右键“发送到 Print”
        ↓
选择“自动识别”或明确的几何类型
        ↓
当前栈帧中的表达式由 occdbg 求值
        ↓
Capture 写入 events.ndjson / BREP
        ↓
Print 增量显示并定位新对象
```

Debug Console 中的 `occdbg point/shape/...` 命令继续保留，用于高级调试和故障回退，但不能替代右键操作的第一版验收。

## 2. 为什么需要 Kit 内的 VS Code 扩展

`launch.json` 只能配置调试启动、环境变量和 LLDB 初始化命令；LLDB Python 插件只能扩展调试器命令。二者都不能向 VS Code 的 Variables/Watch 视图注册右键菜单。

因此在 `freecad-occt-debug-kit` 中增加轻量工作区扩展：

```text
tools/vscode-occ-debug/
├── package.json                 # 命令、菜单、配置和版本约束
├── src/
│   ├── extension.ts             # 生命周期和命令注册
│   ├── contextAdapter.ts        # Variables/Watch 参数适配
│   ├── dapFrameTracker.ts       # variablesReference → FrameLocator
│   ├── geometryKind.ts          # 类型识别和显式类型选择
│   ├── occdbgRequest.ts         # Base64 请求与 CodeLLDB 调用
│   └── status.ts                # Session/Bridge/Print 状态
└── test/
```

扩展只负责 VS Code/CodeLLDB 的交互编排，不包含 OCCT 序列化、Mesh 转换和 Three.js 渲染。它属于 Kit，不属于 Print。

## 3. 第一版交互

### 3.1 Variables 和 Watch

当调试类型为 `lldb` 且进程处于暂停状态时，两个菜单都提供：

- `发送到 Print（自动识别）`
- `发送到 Print：点`
- `发送到 Print：二维点`
- `发送到 Print：曲线`
- `发送到 Print：Edge`
- `发送到 Print：Wire`
- `发送到 Print：Face`
- `发送到 Print：Shape`

常用入口是“自动识别”；明确类型入口用于 Handle、基类引用、模板包装和 LLDB 未返回类型名等歧义场景。相同命令也注册到命令面板，便于键盘操作和测试。

### 3.2 分组和命名

- 默认标签使用变量名或 Watch 表达式的简化文本。
- 默认 group 使用当前调试分组，例如 `fillet/stripe/2`。
- 状态栏显示当前 group，并提供“切换分组”和“清空当前分组”。
- 第一版不在每次发送时强制弹窗；命名或分组需要修改时再调用专门命令。

### 3.3 反馈

成功反馈必须包含类型、对象 ID 和序号，例如：

```text
已发送到 Print：face supportFace · fillet/stripe/2/supportFace · seq=37
```

错误必须可行动：

- 目标进程仍在运行：提示先暂停。
- 表达式已优化掉或离开作用域：显示 CodeLLDB 求值错误。
- 空 Handle：说明已跳过，不生成伪几何。
- Capture 未加载：提供“加载 Capture”操作。
- Bridge/Viewer 未连接：说明事件已写入 Session，启动或重连 Print 后仍会恢复。
- 类型无法识别：弹出明确类型选择，不根据变量名静默猜测。

## 4. VS Code 菜单参数约束

VS Code 提供 `debug/variables/context` 和 `debug/watch/context` 菜单贡献点。右键参数在运行时可序列化为调试协议变量上下文，核心字段如下：

```ts
interface DebugVariableContext {
  sessionId?: string;
  container?: {
    variablesReference?: number;
    expression?: string;
  };
  variable: {
    name: string;
    value: string;
    type?: string;
    evaluateName?: string;
    variablesReference: number;
  };
}
```

实现必须遵守以下规则：

1. Variables 优先使用 `variable.evaluateName`。
2. Watch 使用原始 Watch 表达式，即其 `evaluateName/name`。
3. `value` 只是格式化后的显示文本，不能作为 C++ 表达式执行。
4. 没有可求值表达式时拒绝发送，并提示将合法表达式加入 Watch。
5. 菜单参数不是 VS Code 公共 TypeScript 类型，`contextAdapter` 必须进行结构校验，兼容性测试固定受支持的 VS Code 版本。

## 5. 精确绑定当前栈帧

仅依赖 `vscode.debug.activeDebugSession` 不足以确定变量所属 frame。尤其在多个线程、递归调用或用户切换 Call Stack 后，错误 frame 可能恰好存在同名变量，从而输出错误几何。

第一版使用 VS Code 公开的 `DebugAdapterTracker` 跟踪当前 CodeLLDB 会话的 DAP 消息，维护 `FrameLocator = { frameId, threadId, frameIndex, stopGeneration }`：

```text
stackTrace(threadId, startFrame) response
    response.frame.id ────────────────► threadId + frameIndex

scopes(frameId) response
    scope.variablesReference ─────────► FrameLocator

variables(parentReference) response
    child.variablesReference ─────────► parent FrameLocator

evaluate(expression, frameId) response
    result.variablesReference ─────────► FrameLocator
```

发送时依次用 container、变量和 Watch 求值记录解析 FrameLocator。每次 `continued`、新 `stopped` 或 session 结束时清理过期映射。`occdbg` 除了接收 DAP `frameId`，还使用 payload 中的 `threadId + frameIndex` 显式取得 `SBThread/SBFrame`；这样即使用户曾在 Debug Console 手工执行 `frame select`，也不会把右键变量求值到另一个 frame。

无法可靠恢复 frameId 时：

- 单一候选 frame 可以明确选择后继续；
- 多线程/多 frame 歧义时必须让用户选择 Call Stack frame 或重新展开变量；
- 禁止默认取第一个线程的 top frame 后静默发送。

## 6. 类型识别

自动识别依据 DAP 返回的 `type`，再由 LLDB Python 插件做二次校验。首批规则：

| C++ 类型族 | Print 类型 | 说明 |
| --- | --- | --- |
| `gp_Pnt` | `point` | 三维点 |
| `gp_Pnt2d` | `point2d` | 必须附着到具体 Face/Surface 上下文才具有完整空间意义 |
| `Handle(Geom_Curve)`、`Geom_*Curve` | `curve` | 保存参数范围和采样策略 |
| `TopoDS_Edge` | `edge` | 保留 Orientation、Location 和 Pcurve occurrence |
| `TopoDS_Wire` | `wire` | 保留有序 Edge occurrence |
| `TopoDS_Face` | `face` | BREP 为权威资产，Mesh 为派生显示数据 |
| 其他 `TopoDS_*` | `shape` | Vertex/Shell/Solid/Compound 等统一进入 Shape 路径 |

边界规则：

- `TopoDS_Shape&`、基类指针和 Handle 包装可能无法仅靠字符串判定，进入类型选择。
- `Geom2d_Curve` 不能脱离支撑 Face/Pcurve 语义冒充三维曲线。
- `gp_Vec`、`gp_Dir` 默认不是空间点；后续可增加向量/法向专用渲染器。
- `TopLoc_Location` 必须由 Capture 管线应用一次且仅一次，禁止 Viewer 再重复变换。
- 优化构建中显示为 `<optimized out>` 的变量不可发送；第一版以 Debug 构建为前提。

## 7. 调用协议

扩展不拼接包含用户表达式的裸 LLDB 命令。它先构造请求，再用 UTF-8 Base64 编码，避免空格、引号、模板和 `->` 的转义问题：

```json
{
  "protocol": 1,
  "kind": "face",
  "expression": "HS1->Face()",
  "label": "supportFace",
  "group": "fillet/stripe/2",
  "producer": "lldb-dynamic",
  "trigger": "vscode-variable",
  "frameId": 42,
  "threadId": 77123,
  "frameIndex": 3
}
```

发送给 CodeLLDB 的逻辑命令为：

```text
occdbg emit --request-base64 <payload>
```

扩展通过当前 `DebugSession.customRequest('evaluate', ...)` 调用，并显式传入 `frameId` 和 CodeLLDB 的 `context: '_command'`。该 CodeLLDB 扩展上下文会在指定 frame 执行 LLDB 命令、把命令输出直接放入 evaluate response，并且不受 Debug Console 的 `commands/evaluate` 模式影响。`_command` 不是通用 DAP 标准，因此必须固定并测试 CodeLLDB 版本；若升级后能力探测失败，扩展应拒绝发送并提示版本不兼容。

`occdbg emit` 返回单行机器可读结果，扩展据此显示成功或失败，而不是解析彩色终端日志：

```json
{"ok":true,"entity_id":"fillet/stripe/2/supportFace","seq":37,"persisted":true}
```

## 8. “发送到 Print”的实际数据路径

VS Code 扩展不直接依赖浏览器端口，也不把被调试进程中的 C++ 对象序列化成前端 JSON：

```text
VS Code 右键
  → CodeLLDB 在指定 frame 调用 occdbg
  → LLDB Python / libOccDebugCapture
  → events.ndjson + assets/*.brep
  → Print Bridge tail + 本地 OCCT Mesh
  → SSE
  → Print Scene Store
```

这样可以保持三条重要边界：

- Capture 使用与 FreeCAD 相同的本地 OCCT 版本处理权威 BREP。
- Bridge 或 Print 重启不影响被调试算法，也不会让已落盘事件丢失。
- Agent、Debug Console 和 VS Code 右键最终产生相同协议事件。

## 9. F5 无缝衔接

第一版提供 Kit 工作区调试配置，正常 F5 依次完成：

1. 校验/创建当前 Session，并写入 `.occ-debug/current.env`。
2. 确认 Capture 动态库已构建；仅 API 或实现变化时重建。
3. 启动 Print Bridge；未启动时拉起，已运行时复用。
4. 打开或复用 `http://127.0.0.1:5777/`。
5. CodeLLDB 导入 `lldb_occ_debug.py` 和 OCCT/Qt pretty-printer。
6. launch 模式加载 Capture；attach 模式在进程停止后执行 `occdbg load`。
7. 状态栏显示 `Print: 已连接 · group=<name>`。

“skip build” 配置仍可用于已编译程序；它只能跳过 FreeCAD/OCCT 增量构建，不能跳过 Session、Bridge 和 LLDB 插件初始化。

## 10. 版本与失败边界

第一版发布时固定并验证一个 VS Code + CodeLLDB 组合，不声明对所有历史版本兼容。启动时检查：

- 调试类型必须为 `lldb`。
- CodeLLDB 已安装且版本满足 Kit 锁定范围。
- CodeLLDB 支持返回命令输出的 `_command` evaluate context。
- 当前 sessionId 与菜单变量上下文一致。
- 目标为 stopped 状态，frame 映射仍属于当前 stop generation。
- Session 可写，Capture 协议版本与 Print 协议兼容。

任何检查失败都应停止发送并说明原因。扩展不得在目标运行时强行求值，也不得自动恢复/暂停进程来完成一次发送。

## 11. 测试计划

单元测试：

- Variables/Watch 参数的结构校验和表达式提取。
- 类型字符串规范化、自动识别和歧义回退。
- Base64 请求对模板、引号、空格和 Unicode 标签的无损编码。
- DAP stackTrace/scopes/variables/evaluate 映射的递归继承和 stop generation 清理。

CodeLLDB 集成测试：

- 局部 `gp_Pnt`、嵌套成员 `gp_Pnt`、Watch `builder.Shape()`。
- `TopoDS_Edge/Face/Shape`、空 Handle、Null Shape 和 `<optimized out>`。
- 同名变量存在于不同递归 frame。
- 多线程停止后从非 top frame 发送。
- Debug Console 手工 `frame select` 后，右键变量仍使用记录的 thread/frame。
- `commands` 与 `evaluate` console mode。
- Bridge 离线时先落盘，重连后 Print 恢复对象。
- Viewer 在线时发送到可见的新增对象延迟目标小于 500 ms。

## 12. 第一版验收标准

以下各项必须全部通过，才能称为第一版闭环完成：

1. Variables 中右键 `gp_Pnt`，无需改源码或重新编译即可在 Print 增量出现。
2. Watch 中右键 `builder.Shape()`，可生成 BREP 并在 Print 显示。
3. Variables 和 Watch 都提供自动类型与显式类型入口。
4. 递归 frame 和多线程场景不会静默求值到错误 frame。
5. 空 Handle、优化掉的变量、运行态目标和 Capture 未加载都有明确反馈。
6. 分组、清空、对象命名与 Debug Console 的 `occdbg` 命令一致。
7. Bridge/Viewer 暂时离线时事件仍持久化，恢复后可显示。
8. 正常 F5 自动准备 Session、Bridge、Print 和 LLDB 插件。

这组能力是 MVP 的必要组成，不放入“后续增强”。后续增强只包括批量多选发送、Hover/编辑器选区入口、调试时间轴和 Agent 对 VS Code UI 的高层控制。

## 13. 实现依据

- [VS Code 菜单贡献点](https://code.visualstudio.com/api/references/contribution-points#contributes.menus)：Variables/Watch 右键菜单注册方式。
- [VS Code Debug API](https://code.visualstudio.com/api/references/vscode-api#debug)：活动调试会话、`customRequest` 和调试生命周期。
- [VS Code DebugAdapterTracker API](https://code.visualstudio.com/api/references/vscode-api#DebugAdapterTracker)：观察 DAP 请求/响应并建立 frame 映射。
- [CodeLLDB Manual](https://github.com/vadimcn/codelldb/blob/master/MANUAL.md)：`initCommands`、`preRunCommands`、`postRunCommands` 和 Debug Console 模式。

开发时以 Kit 锁定版本对应的源码/API 为准；升级 VS Code 或 CodeLLDB 时必须重跑第 11 节的菜单参数和 frame 集成测试。
