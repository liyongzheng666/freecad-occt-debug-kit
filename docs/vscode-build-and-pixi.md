# VS Code 里的编译 / 链接是怎么跑起来的（含 Pixi 详解）

这篇文档解释本仓库（外层 `freecad/` 工作区）在 VS Code 中如何完成 **配置 → 编译 → 链接 → 运行/调试** 的整条链路，并重点说明 **Pixi** 在其中扮演的角色。

---

## 0. 一句话总览

> **Pixi** 提供一套锁定的工具链与依赖（clang / cmake / ninja / Qt / OCCT…），放在 `FreeCAD/.pixi/envs/default`。
> 所有编译命令都用 `pixi run -- …` 包起来，让它们运行在这套环境里。
> VS Code 只是“调度层”——`tasks.json` 负责编译、`launch.json` 负责调试、`.clangd` 负责补全，三者最终都指向 Pixi 环境和两个构建目录。

整个工作区其实是 **两个独立源码仓库** 被一层 VS Code 配置粘在一起：

```text
freecad/                      ← 外层编排层（本仓库，VS Code 在这里打开）
├── FreeCAD/                  ← FreeCAD 源码 + Pixi 环境 + Ninja 构建 (build/debug)
│   └── .pixi/envs/default/   ← 锁定的编译器 / 依赖（编译实际发生的环境）
├── occt/                     ← OCCT 源码 + Makefiles 构建 + 本地 install
│   ├── build/debug/          ← OCCT 的 Debug 构建目录
│   └── install/debug/        ← 带调试符号、可改源码的本地 OCCT
├── scripts/                  ← configure / build / run / debug 入口脚本
├── .vscode/                  ← 唯一一套 VS Code 配置，同时服务两个仓库
└── docs/                     ← 本文档所在
```

**为什么要这么折腾？** Pixi 自带一份预编译的 release 版 OCCT（`occt 7.8`），但你没法 step 进它的源码、也改不了它的逻辑。所以本工作区单独编了一份 **本地 Debug OCCT**（`occt/install/debug`），让 FreeCAD 链接它而不是 Pixi 里那份——这样就能在 OCCT 内部（比如圆角算法 `BRepFilletAPI_MakeFillet`）下断点、单步、改代码重编。

---

## 预备知识：6 个概念（第一次接触 Pixi / CMake 必读）

如果你是 C++ 工程师但没怎么用过 CMake / Pixi，先花 5 分钟把下面 6 个词搞清楚，后面就都顺了。已经熟的可以跳过。

### ① C++ 程序是怎么从源码变成可执行文件的

两步：**编译（compile）** 把每个 `.cpp` 单独翻译成机器码 `.o`；**链接（link）** 把所有 `.o` 和它依赖的**库**拼成最终的可执行文件或库。

- **库**有两种：`.a`（静态库，编译期被塞进可执行文件）和 `.dylib`/`.so`/`.dll`（**动态库**，运行时才加载）。本项目里 Qt、Boost、OCCT 全是动态库（macOS 上是 `.dylib`）。
- 记住这个区别，第 4 节讲“链接顺序”和“运行时找不到库”才有意义。

### ② CMake 不是编译器，是“生成构建脚本的工具”

很多人第一次的误解：以为 `cmake` 自己在编译。其实不是。CMake 干的是**两步走**：

1. **Configure（配置）**：读 `CMakeLists.txt`，探测“你机器上编译器在哪、库在哪”，然后**生成真正的构建脚本**（Makefile 或 Ninja 文件）。这一步产物放在**构建目录**（如 `build/debug`）。
2. **Build（构建）**：调用上一步生成的脚本，真正调编译器去编、去链接。

命令上就是这两条：
```bash
cmake --preset xxx          # ① 配置：生成构建目录
cmake --build build/debug   # ② 构建：真正编译链接
```

还有可选的第三步 **Install（安装）**：`cmake --install`，把编好的库/头文件拷到一个“安装目录”（本项目 OCCT 就是装到 `occt/install/debug`，好让 FreeCAD 去链接）。

> **源码目录 vs 构建目录**：CMake 强烈推荐“out-of-source build”——源码一个目录，生成物全扔进另一个 `build/` 目录，互不污染。本项目 `FreeCAD/build/debug`、`occt/build/debug` 就是构建目录。

### ③ 生成器（Generator）：Makefiles 还是 Ninja

Configure 时 CMake 可以生成不同格式的构建脚本，这叫**生成器**：
- **Unix Makefiles** —— 老牌，生成 `Makefile`，用 `make` 跑。本项目 OCCT 用它。
- **Ninja** —— 更快的现代替代品，本项目 FreeCAD 用它。

对你来说差别不大，知道“它俩是同一层东西、只是构建脚本的两种方言”就够了。两者都来自 Pixi 环境，不用自己装。

### ④ Preset（预设）与 Cache 变量：把一长串 cmake 参数存成名字

Configure 时经常要传几十个 `-DXXX=YYY` 参数（编译类型、库路径、开关……），手敲容易错。**CMake Preset** 就是把这些参数写进 `CMakePresets.json`，起个名字，以后 `cmake --preset 名字` 一把梭。Preset 之间还能**继承**（`inherits`），像类继承一样层层叠加。

那些 `-DXXX=YYY` 设的值叫 **cache 变量**——它们被记在构建目录的 `CMakeCache.txt` 里，第二次 configure 会复用。常见的：
- `CMAKE_BUILD_TYPE=Debug` —— 编 Debug 版（带调试符号、不优化）。
- `CMAKE_INSTALL_PREFIX=...` —— install 时装到哪。
- `CMAKE_CXX_COMPILER=...` —— 用哪个 clang++。

### ⑤ `compile_commands.json`：给编辑器看的“每个文件怎么编”的清单

Configure 时加一个开关 `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`，CMake 会额外吐出一个 `compile_commands.json`（业内简称 **CDB**，compilation database）。它逐条记录“编译每个 `.cpp` 时用了哪些 `-I 头文件路径`、`-D 宏`、`-std` 标准……”。

**clangd**（代码补全/跳转引擎）就靠读这个文件，才能准确地给你补全、跳转、标红。所以本项目反复强调：**没 configure 过 → 没有 CDB → clangd 一堆假报错**。

### ⑥ RPATH 与 `DYLD_LIBRARY_PATH`：运行时怎么找到 `.dylib`

动态库是运行时才加载的，那程序怎么知道去哪找 `libTKernel.dylib`？操作系统的动态链接器（macOS 叫 **dyld**）按几个来源依次找：

- **RPATH** —— 链接时**写死在可执行文件内部**的一串搜索路径。CMake 里用 `CMAKE_BUILD_RPATH` 设。
- **`DYLD_LIBRARY_PATH`** —— 一个环境变量，运行前临时指定额外搜索路径（Linux 上对应 `LD_LIBRARY_PATH`）。优先级高、常用来“兜底/覆盖”。

本项目的核心小动作就是：让“本地 Debug OCCT 的 lib 目录”在 RPATH 和 `DYLD_LIBRARY_PATH` 里都**排在 Pixi 那份的前面**，从而加载到带调试符号、可改的那份 OCCT。详见第 4 节。

---

有了这 6 个概念，下面正式开始。

---

## 1. Pixi 是什么，在这里干什么

### 1.1 Pixi 是什么

Pixi 是一个基于 **conda-forge** 生态的跨平台包管理 / 环境管理器（类似 `conda` + `cargo` 的混合体）。

**用你可能熟悉的工具类比一下**：

| 你以前可能用 | 痛点 | Pixi 怎么解决 |
|---|---|---|
| `apt` / `brew` 装库 | 全局安装，版本一台机器一个样，换台机器就崩 | 依赖装在**项目目录内**，锁定版本，换机器一模一样 |
| 手动 `./configure && make` 装依赖 | 编译半天、版本难控 | conda-forge 都是**预编译好的二进制**，直接下载即用 |
| Python 的 `venv` / `requirements.txt` | 只管 Python 包，管不了 C++ 库和编译器 | 连 **clang、cmake、Qt、Boost** 这种 C/C++ 工具链都能装 |

> **conda-forge** 是一个社区维护的超大软件仓库（“频道”），里面是各平台预编译好的包。Pixi 默认从这里拉东西（见 `pixi.toml` 的 `channels = ["conda-forge"]`）。

它的核心理念，三句话：

- **声明式**：`pixi.toml` 里写“我要哪些依赖”，`pixi.lock` 自动锁定到**具体版本和哈希**——任何人、任何机器都复现出**完全一致**的环境（解决了 C++ 项目最头疼的“在我机器上能编”）。
- **项目本地**：所有东西装在项目目录下的 `.pixi/envs/`，**不污染全局**，也**不需要** `conda activate` 那种切换。
- **任务运行器**：`pixi run <命令>` 会在这套环境里执行命令，自动把环境的 `PATH`、`CONDA_PREFIX`、库搜索路径都设好——你不用手动 source 任何脚本。

本机版本：`pixi 0.68.0`（`pixi.toml` 要求 `requires-pixi >= 0.48`）。

> **直观理解 `.pixi/envs/default`**：可以把它想成“一个装在项目文件夹里的迷你 Linux/macOS 系统根目录”——`bin/` 里有 clang、cmake、ninja，`lib/` 里有 Qt、Boost、OCCT 的 `.dylib`，`include/` 里有头文件。`pixi run` 做的事，本质就是临时把这个迷你系统的 `bin`/`lib` 接到你的命令前面。

### 1.2 本仓库的 Pixi 配置（`FreeCAD/pixi.toml`）

```toml
[workspace]
name = "FreeCAD"
channels = ["conda-forge"]
platforms = ["linux-64", "linux-aarch64", "osx-64", "osx-arm64", "win-64"]

[dependencies]
compilers = ">=1.10,<1.11"   # ← clang / clang++ 工具链
cmake = "*"
ninja = "*"                  # ← FreeCAD 用的构建后端
occt = ">=7.8,<7.9"          # ← Pixi 自带的 release OCCT（本地 debug 版会覆盖它）
qt6-main = ">=6.8,<6.9"
pyside6 = "*"
python = ">=3.11,<3.12"
# …以及 boost / vtk / coin3d / eigen / tbb / pcl 等一大票 C++/Python 依赖
```

关键点：

- **编译器来自 Pixi**：`compilers` 这个 meta 包在 macOS arm64 上提供
  `arm64-apple-darwin20.0.0-clang` / `…-clang++`（见 `scripts/configure-occt.sh` 里直接点名用它）。
- **所有第三方库来自 Pixi**：FreeCAD 链接的 Qt6、Boost、VTK、Python 等全部在 `.pixi/envs/default/lib`。
- **`occt` 也在依赖里**，但仅作 fallback——真正用的是本地 Debug 版（见第 4 节链接顺序）。

### 1.3 `pixi.toml` 里的 tasks（命令行用，VS Code 没直接用）

`pixi.toml` 底部定义了一组跨平台任务，平时在 `FreeCAD/` 目录手敲时方便：

```toml
[tasks]
configure = [{ task = "configure-debug" }]   # cmake --preset conda-macos-debug
build     = [{ task = "build-debug" }]        # cmake --build build/debug
install   = [{ task = "install-debug" }]
freecad   = [{ task = "freecad-debug" }]      # 跑 build/debug/bin/FreeCAD
```

> 注意：**VS Code 的 task 并没有调用这些 pixi task**，而是直接 `pixi run -- cmake --preset local-occt-macos-debug`（用的是本地 OCCT 的 user preset，见第 3 节）。两者目的相同，但 VS Code 走的是“本地 Debug OCCT”那条线。

### 1.4 `pixi run --frozen --` 这串前缀的含义

仓库里所有编译/运行命令都是这个形状：

```bash
pixi run --frozen -- <真正要跑的命令>
```

- `pixi run` —— 在 `.pixi/envs/default` 环境里执行后面的命令（自动设好 `PATH` / `CONDA_PREFIX` / 库路径）。
- `--frozen` —— **只用现有的 `pixi.lock`，绝不自动改/装包**。保证编译环境稳定、可复现，不会因为联网解析依赖而变动。
- `--` —— 分隔符，后面的东西原样传给环境里的程序（`cmake` / `lldb` / `env …`）。

---

## 2. 两个构建系统：FreeCAD vs OCCT

本工作区故意用了两套不同的构建方式，对应两个仓库：

| | FreeCAD | OCCT |
|---|---|---|
| 生成器 | **Ninja**（来自 Pixi） | **Unix Makefiles** |
| 配置入口 | `cmake --preset local-occt-macos-debug` | `scripts/configure-occt.sh` |
| 构建目录 | `FreeCAD/build/debug` | `occt/build/debug` |
| 编译命令 | `pixi run -- cmake --build build/debug -j 8` | `pixi run -- cmake --build … --target install` |
| 产物 | `build/debug/bin/FreeCAD(Cmd)` | 安装到 `occt/install/debug` |
| 谁链接谁 | FreeCAD **链接** 本地 OCCT | 被 FreeCAD 链接 |

两者都跑在 **同一个 Pixi 环境**里（同一套 clang），所以 ABI 兼容。OCCT 用 Makefiles 是因为它的 `install` 目标能“先增量重编有改动的目标，再安装”，配合 `rebuild-occ.sh` 实现“改了 OCCT 源码 → 只编你改的 → FreeCAD 下次启动即生效”。

---

## 3. CMake 预设链（配置阶段）

> 回忆预备知识 ④：Preset 就是“把一长串 cmake 参数存成名字 + 支持继承”。下面这条链就是一层层继承叠加上来的，读法是**从下往上看**：最底层定通用开关，越往上越具体。

FreeCAD 的配置通过 CMake Preset 完成，是一条继承链：

```
local-occt-macos-debug   (FreeCAD/CMakeUserPresets.json，本地专属、不进版本库)
  └─ inherits: conda-macos-debug   (FreeCAD/CMakePresets.json，官方)
       ├─ conda-debug → debug    → binaryDir = build/debug, CMAKE_BUILD_TYPE=Debug
       │              → conda     → 生成器=Ninja, BUILD_WITH_CONDA=ON, …
       └─ conda-macos             → CMAKE_PREFIX_PATH=$CONDA_PREFIX, 忽略 Homebrew
```

`local-occt-macos-debug` 在继承官方 conda 预设的基础上，**把 OCCT 的查找路径全部重定向到本地 Debug 安装**：

```jsonc
// FreeCAD/CMakeUserPresets.json（节选）
"OCC_INCLUDE_DIR":        ".../occt/install/debug/include/opencascade",
"OCC_LIBRARY_DIR":        ".../occt/install/debug/lib",
"OpenCASCADE_DIR":        ".../occt/install/debug/lib/cmake/opencascade",
"CMAKE_BUILD_RPATH":      ".../occt/install/debug/lib;.../.pixi/envs/default/lib",
"CMAKE_EXE_LINKER_FLAGS": "-L.../occt/install/debug/lib -Wl,-headerpad_max_install_names -Wl,-dead_strip_dylibs -L.../.pixi/envs/default/lib"
// SHARED / MODULE 的 linker flags 同理
```

> `${sourceParentDir}` = `freecad/`，`${sourceDir}` = `freecad/FreeCAD/`。所以这些路径在你挪动整个工作区后依然成立。

OCCT 这边没有 preset，直接在 `scripts/configure-occt.sh` 里用裸 `cmake`：

```bash
pixi run --frozen -- cmake \
  -S occt -B occt/build/debug -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_INSTALL_PREFIX=occt/install/debug \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \           # ← 给 clangd 用
  -DCMAKE_C_COMPILER=.../bin/arm64-apple-darwin20.0.0-clang \    # ← Pixi 的 clang
  -DCMAKE_CXX_COMPILER=.../bin/arm64-apple-darwin20.0.0-clang++ \
  -DCMAKE_CXX_FLAGS_DEBUG="-g -O0 -fno-omit-frame-pointer"       # ← 完整调试符号、不优化
```

---

## 4. 链接与运行时库解析（最容易踩坑的部分）

目标：让 FreeCAD **链接并加载本地 Debug OCCT**，而不是 Pixi 里那份 release OCCT。这是通过三道防线保证的：

1. **链接期搜索顺序**（`CMAKE_*_LINKER_FLAGS`）
   `-L .../occt/install/debug/lib` 写在 `-L .../.pixi/envs/default/lib` **之前**，所以链接器优先选本地 Debug 的 `libTK*.dylib`。

2. **可执行文件内嵌的 RPATH**（`CMAKE_BUILD_RPATH`）
   `occt/install/debug/lib` 排在 Pixi lib **之前**。运行时 dyld 按这个顺序找 `.dylib`，本地 Debug 版胜出。

3. **运行时环境变量兜底**（`DYLD_LIBRARY_PATH`）
   即使 RPATH 出问题，所有运行/调试入口都会再把 `occt/install/debug/lib` 塞进 `DYLD_LIBRARY_PATH`：
   - `launch.json` 的每个 launch 配置里 `"env": { "DYLD_LIBRARY_PATH": "${workspaceFolder}/occt/install/debug/lib:…" }`
   - `scripts/fc-cmd.sh` / `fc-gui.sh` / `fc-lldb.sh` 里 `env DYLD_LIBRARY_PATH="$LOCAL_OCC_LIB" …`

其余链接器标志的作用：
- `-Wl,-headerpad_max_install_names` —— 给 Mach-O 头预留空间，方便事后用 `install_name_tool` 改库路径。
- `-Wl,-dead_strip_dylibs` —— 丢掉没真正用到的 dylib 依赖，减少无谓加载。

---

## 5. VS Code 是怎么把这些串起来的

### 5.1 `tasks.json` —— 编译入口

定义了细粒度 task，再用两个“组合 task”串起来：

| Task | 实际做什么 |
|---|---|
| `OCCT: configure debug` | 跑 `scripts/configure-occt.sh` |
| `OCCT: build + install debug` | 跑 `scripts/rebuild-occ.sh`（增量重编 + 安装本地 OCCT） |
| `FreeCAD: configure local OCCT debug` | `pixi run -- cmake --preset local-occt-macos-debug`（cwd=`FreeCAD/`） |
| `FreeCAD: build debug` | `pixi run -- cmake --build build/debug -j 8` |
| **`Workspace: configure debug`** | 顺序执行：OCCT configure → FreeCAD configure |
| **`Debug: sync local toolchain`** | 顺序执行：OCCT build+install → FreeCAD build　**（默认 build task）** |
| `Workspace: doctor` | 跑 `scripts/workspace-doctor.sh` 体检 |

- `"problemMatcher": ["$gcc"]` —— 让 clang 的报错/警告被解析进 VS Code 的 **Problems** 面板，可点击跳转。
- `Debug: sync local toolchain` 被标成 `"group": { "kind": "build", "isDefault": true }`，所以 **⌘B** 直接触发它。

### 5.2 `launch.json` —— 调试入口（CodeLLDB）

5 个配置，前 4 个都把 `preLaunchTask` 设为 **`Debug: sync local toolchain`**——意味着 **每次 F5 调试前，会自动先把 OCCT 和 FreeCAD 都增量重编一遍**，保证你调的是最新代码。

```jsonc
{
  "type": "lldb",                    // vadimcn.vscode-lldb (CodeLLDB)
  "name": "FreeCAD GUI · local OCCT · build first",
  "program": "${workspaceFolder}/FreeCAD/build/debug/bin/FreeCAD",
  "preLaunchTask": "Debug: sync local toolchain",   // ← 先编后调
  "env": { "DYLD_LIBRARY_PATH": "${workspaceFolder}/occt/install/debug/lib:…" },
  "initCommands": [
    "settings set target.process.thread.step-avoid-regexp ^(std::|boost::|Py|Qt|…)",  // 单步时跳过库内部
    "command script import ${workspaceFolder}/scripts/lldb_occt_formatters.py",        // OCCT 类型的漂亮打印
    "command script import .../FreeCAD/contrib/debugger/qt_pretty_printers_lldb.py"    // Qt 类型的漂亮打印
  ]
}
```

- 唯一一个名字带 **`skip build`** 的配置**没有** `preLaunchTask`——用于附加/检查“已经编好”的进程，省去重编时间。
- 还有一个 `request: "attach"` 配置，可 attach 到正在跑的 FreeCAD（`${command:pickProcess}` 选 PID）。

### 5.3 `settings.json` + `.clangd` —— 代码补全 / 跳转（IntelliSense）

本工作区**关掉了微软的 C/C++ 引擎，改用 clangd**：

```jsonc
// .vscode/settings.json
"C_Cpp.intelliSenseEngine": "disabled",
"clangd.path": "/usr/bin/clangd",
"clangd.arguments": [
  "--background-index",
  "--query-driver=${workspaceFolder}/FreeCAD/.pixi/envs/default/bin/*clang*",  // ← 让 clangd 认识 Pixi 的 clang
  …
]
```

clangd 怎么知道每个文件的编译参数？靠 `.clangd` 做**按路径分流**到各自的 compilation database：

```yaml
# .clangd
If: { PathMatch: FreeCAD/.* }
CompileFlags: { CompilationDatabase: FreeCAD/build/debug }   # ← Ninja 生成的 compile_commands.json
---
If: { PathMatch: occt/.* }
CompileFlags: { CompilationDatabase: occt/build/debug }      # ← configure 时 -DCMAKE_EXPORT_COMPILE_COMMANDS=ON 生成
```

所以：**必须先 configure 一次（生成 `compile_commands.json`），clangd 的补全/跳转/报错才准确**。

另外 `settings.json` 还把生成目录排除出搜索和文件监视，避免卡顿：

```jsonc
"files.watcherExclude": { "**/FreeCAD/.pixi/**": true, "**/FreeCAD/build/**": true, "**/occt/build/**": true, … },
"cmake.buildDirectory": "${workspaceFolder}/FreeCAD/build/debug"
```

### 5.4 `extensions.json` —— 推荐扩展

打开工作区时 VS Code 会提示安装：

| 扩展 | 作用 |
|---|---|
| `llvm-vs-code-extensions.vscode-clangd` | C++ 补全 / 跳转 / 诊断（替代微软引擎） |
| `vadimcn.vscode-lldb` (CodeLLDB) | `launch.json` 的 `lldb` 调试类型 |
| `ms-vscode.cmake-tools` | CMake 集成 |
| `loukas-kotas.breakpoints-manager` | 断点分组管理 |
| `hediet.debug-visualizer` | 调试时数据可视化 |

---

## 6. 完整数据流图

```text
                ┌─────────────────────── Pixi 环境 (.pixi/envs/default) ───────────────────────┐
                │   clang / clang++   ·   cmake   ·   ninja   ·   Qt6 / Boost / VTK / Python …    │
                └──────────────────────────────────▲──────────────────────────────────────────┘
                                                    │  所有命令都 pixi run --frozen -- 包进来
   ┌── 配置 ────────────────────────────────────────┼────────────────────────────────────────────┐
   │  OCCT:  configure-occt.sh  ──(Unix Makefiles)──┤   FreeCAD: cmake --preset local-occt-macos-debug
   │     → occt/build/debug/compile_commands.json   │      → FreeCAD/build/debug (Ninja) + compile_commands.json
   └────────────────────────────────────────────────┼────────────────────────────────────────────┘
                                                    │
   ┌── 编译 (⌘B / F5 前自动: "Debug: sync local toolchain") ───────────────────────────────────────┐
   │  rebuild-occ.sh: cmake --build … --target install                                            │
   │     → occt/install/debug/lib/libTK*.dylib  (带 -g -O0 调试符号)                                │
   │  FreeCAD: cmake --build build/debug -j 8                                                      │
   │     → build/debug/bin/FreeCAD(Cmd)，链接顺序: 本地OCCT lib  >  Pixi lib                          │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘
                                                    │
   ┌── 运行 / 调试 ─────────────────────────────────────────────────────────────────────────────────┐
   │  CodeLLDB (launch.json) 或 scripts/fc-*.sh                                                     │
   │     env DYLD_LIBRARY_PATH = occt/install/debug/lib  (兜底，确保加载本地 Debug OCCT)              │
   │     + 导入 lldb 的 OCCT / Qt pretty-printer                                                     │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘
                                                    ▲
   clangd (.clangd) 读两个 compile_commands.json，按路径分流，提供补全/跳转/诊断 ─────────────────────┘
```

---

## 7. 常见操作速查

```bash
# 体检（先跑这个，确认环境就绪）
scripts/workspace-doctor.sh
scripts/workspace-doctor.sh --runtime    # 额外检查动态库解析

# 命令行手动走一遍（VS Code task 等价物）
scripts/configure-occt.sh                # 配置 OCCT + 生成 CDB
scripts/rebuild-occ.sh                   # 增量重编 + 安装本地 OCCT
cd FreeCAD && pixi run --frozen -- cmake --preset local-occt-macos-debug
cd FreeCAD && pixi run --frozen -- cmake --build build/debug -j 8

# 运行
scripts/fc-cmd.sh scripts/debug_target.py     # 控制台版 FreeCADCmd（跑脚本）
scripts/fc-gui.sh                              # GUI 版
scripts/fc-lldb.sh scripts/debug_target.py    # 命令行 lldb 调试
```

**在 VS Code 里：**
- **⌘B** → 触发默认 build task `Debug: sync local toolchain`（OCCT + FreeCAD 全量增量重编）。
- **F5** → 选一个 launch 配置；带 “build first” 的会先自动编译，带 “skip build” 的直接调已编好的进程。
- 终端里 **Tasks: Run Task** 可单独跑 configure / doctor 等。

---

## 8. 几条不要踩的坑

- **必须打开外层 `freecad/` 目录**，而不是单独打开 `FreeCAD/` 或 `occt/`——`.clangd`、`.vscode/`、`scripts/` 的相对路径都基于外层。
- **别把 `.pixi/`、`build/`、`install/` 当垃圾删**。删了 `.pixi` = 整个工具链没了；删了 `install/debug` = 没有本地 Debug OCCT 可链接。它们已被 `.gitignore` 和 watcher 排除，正常情况下不该动。
- **改了 OCCT 源码后要 `rebuild-occ.sh`（或 ⌘B）**，否则 FreeCAD 仍加载旧的 `install/debug` 库。
- **配置必须先于补全**：没跑过 configure 就没有 `compile_commands.json`，clangd 会报一堆找不到头文件的假错。
- 外层 Git 仓库**故意忽略** `FreeCAD/` 和 `occt/`，它们各自有自己的分支和远程——别在外层仓库里提交它们的改动。

---

参考：调试细节见 [`docs/occt-debugging.md`](./occt-debugging.md) 与 [`docs/vscode-debug-breakpoints.md`](./vscode-debug-breakpoints.md)。
