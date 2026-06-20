# FreeCAD Topological Naming (Toponaming) — 架构与实现

> 本文档面向 FreeCAD 内核开发者,梳理 `src/App/` 与 `src/Mod/Part/App/` 中
> 拓扑命名(Topological Naming, 简称 toponaming)的完整实现。所有引用都给出
> `文件:行号`,基于本仓库 `main` 分支当前 HEAD。

---

## 0. 为什么需要 Toponaming

OpenCASCADE 的 `TopoDS_Shape` 只描述"这是一个面/边",**不提供持久身份**。`TopExp_Explorer`
枚举出来的"第几号面"在每次 Boolean / Fillet / Pad 之后都可能改变。如果上层应用直接保存
"Face3" 这种序号引用,一旦下游特征改变拓扑,所有引用就会指向错误的元素 — 即所谓
"toponaming problem"。

FreeCAD 的解法:**不依赖 OCC 序号,自行维护一张"映射名 ↔ 当前序号名"的双向表
(`ElementMap`),把每个 sub-shape 的"出身履历"编码进字符串名字,在每次特征执行时
通过 OCC 给出的 `Modified`/`Generated` 历史增量写入新名字。**

当前编码方案版本号:`Part::OpCodes::Version = 15`,定义在
`src/Mod/Part/App/TopoShapeOpCode.h:49`。打开使用旧版本编码保存的文件会触发整张
element map 重建。

---

## 1. 核心数据类型

### 1.1 `MappedName` — 映射名本体
`src/App/MappedName.h:40-100`

```
MappedName = data (QByteArray) + postfix (QByteArray)
```
- `data`:不可变核心,通常是源元素 ID(如 `E1`)或哈希引用(`#1b`)
- `postfix`:可追加后缀,记录"我是谁生成/修改的、属于哪个对象"

支持 `fromRawData()` 零拷贝包装,在批量构造短名字时非常关键。
序列化时直接将 `data + postfix` 拼接写入流。

### 1.2 `IndexedName` — 当前序号名
`src/App/MappedElement.h`

`<类型字符串, 整数序号>` 对,如 `("Face", 3)` ↔ `Face3`。这是用户/UI 看到的形态,
也是 OCC `TopExp_Explorer` 给出的序号。

### 1.3 `MappedElement` — 配对
`src/App/MappedElement.h`

`MappedName + IndexedName`,代表"这个稳定名当前指向哪个序号面"。
所有上层 API(如 `GeoFeature::getElementName`)返回的都是这个配对。

### 1.4 编码字典 — `src/App/ElementNamingUtils.h:51-92`

| 常量 | 字面 | 含义 |
|---|---|---|
| `ELEMENT_MAP_PREFIX` | `;` | 任何 mapped name 的起始标志 |
| `MAPPED_CHILD_ELEMENTS_PREFIX` | `;:R` | 子元素引用 |
| `POSTFIX_TAG` | `;:H` | 后接对象 Tag(16 进制),区分作者 |
| `POSTFIX_DECIMAL_TAG` | `;:T` | 十进制 Tag(罕用) |
| `POSTFIX_EXTERNAL_TAG` | `;:X` | 外部对象 Tag |
| `POSTFIX_CHILD` | `;:C` | 子元素标记 |
| `POSTFIX_INDEX` | `;:I` | 数组元素索引 |
| `POSTFIX_UPPER` | `;:U` | 由上层元素(面→边)派生 |
| `POSTFIX_LOWER` | `;:L` | 由下层元素(边→面)派生 |
| `POSTFIX_MOD` | `;:M` | OCC 报告的 Modified 元素 |
| `POSTFIX_GEN` | `;:G` | OCC 报告的 Generated 元素 |
| `POSTFIX_MODGEN` | `;:MG` | 既被修改又被生成 |
| `POSTFIX_DUPLICATE` | `;D` | 重复元素 |

> 看懂这张表就基本看懂了 mapped name 的字面含义。一个完整名字例如:
> `;E5;:G;:H38:2,F` 解读为:**源边 E5、被生成、来自 Tag=0x38、起始偏移 2、类型 F(面)**。

### 1.5 `ElementMap` — 双向表 + 父子链
`src/App/ElementMap.h:80-399`,实现 `src/App/ElementMap.cpp`(1484 行)

内部双表:
```cpp
std::map<IndexedName, IndexedElements> indexedNames;  // 正向: Face1 → [MappedName...]
std::map<MappedName,   IndexedName>    mappedNames;   // 反向: MappedName → Face1
```
- 一个 `IndexedName` 可以有**多个别名**(`std::deque<MappedNameRef>`),用于来自不同
  源特征的同一物理面。
- `MappedChildElements` 字段通过 `shared_ptr<ElementMap>` **链接到父特征的映射表**,
  形成历史链 — 不复制,共享。

核心 API:
| 方法 | 作用 |
|---|---|
| `setElementName(idx, mapped, masterTag, sids)` | 注册一对映射 |
| `find(MappedName)` / `find(IndexedName)` | 双向查找 |
| `encodeElementName(type, name, ss, sids, masterTag, op, tag, forceTag)` | 把 op 码 + Tag 追加到名字 |
| `hashElementName(name, sids)` | 通过 StringHasher 把长名字压成 `#<id>` |
| `save()` / `restore()` | 持久化(见 §6) |

### 1.6 `ComplexGeoData` — 持有 ElementMap 的基类
`src/App/ComplexGeoData.h:90-585`

```cpp
mutable long       Tag {0};       // 文档对象 ID; 负值=中间形状
ElementMapPtr      elementMap();  // 元素映射表(共享, 写时拷贝)
StringHasherRef    Hasher;        // 字符串哈希器,见 §5
```
`TopoShape` 继承自 `ComplexGeoData`,所以**每个 TopoShape 都自带 Tag + ElementMap +
Hasher**。

---

## 2. 中央构造入口:`TopoShape::makeShapeWithElementMap`

这是整个 toponaming 体系的**心脏**。任何会改变形状拓扑的操作最终都汇聚到它。

签名 — `src/Mod/Part/App/TopoShape.h:1861-1866`:

```cpp
TopoShape& makeShapeWithElementMap(
    const TopoDS_Shape&            shape,    // 新形状(已由 OCC 算好)
    const Mapper&                  mapper,   // 输入→输出的 modified/generated 映射
    const std::vector<TopoShape>&  sources,  // 输入 TopoShape 们(各自带 ElementMap)
    const char*                    op = nullptr  // 操作码 "FUS"/"XTR"/"FLT"...
);
```

`Mapper` 基类在 `TopoShape.h:1719-1735`,只有两个虚函数:
```cpp
virtual const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape&) const;
virtual const std::vector<TopoDS_Shape>& modified(const TopoDS_Shape&) const;
```

具体实现:
- `MapperMaker` — `TopoShape.h:3021` — 包 `BRepBuilderAPI_MakeShape`(Fillet/Chamfer/Prism 等)
- `MapperSewing` — `TopoShape.h:3031` — 包 `BRepBuilderAPI_Sewing`
- `MapperHistory` — `TopoShape.h:3045` — 包 `BRepTools_History`/`BRepTools_ReShape`/`ShapeFix_Root`

### 2.1 算法三阶段

实现在 `src/Mod/Part/App/TopoShapeExpansion.cpp:1408-1992`,分三阶段。

#### 阶段 ① — 收集 Modified / Generated(`:1467-1641`)

按 Vertex → Edge → Face 顺序遍历每个 source 的已命名元素,询问 `mapper`:
```cpp
for (auto& newShape : mapper.modified(otherElement))  // [:1490]
for (auto& newShape : mapper.generated(otherElement)) // [:1548]
```

- **Modified**:输入元素**变形成同类型**的新元素(如边变形为新边)→ `name_type = 1`
- **Generated**:输入元素**派生出可能不同类型**的新元素(如边→面)→ `name_type = 2`

每条候选记入 `newNames[IndexedName][NameKey] = NameInfo`,带上 `incomingShape.Tag`。

**特殊情况**(`:1566-1599`):extrude 时 OCC 会把整个 solid 报告为某个面"生成"出来。
这种"高层映射"会用 `shapeOffset = 3` 标记,在 ② 中**延后处理**,优先使用更精确的低层映射。

#### 阶段 ② — 主编码循环(`:1648-1798`)

对每个 `IndexedName` 选一个 first source name,根据 `name_type` 拼接后缀:

```cpp
if (name_type == 2)      ss << genPostfix();      // ";:G"
else if (name_type == 1) ss << modPostfix();      // ";:M"
else                     ss << modgenPostfix();   // ";:MG"
```

若同一目标元素有多个 source(如 fuse 出来的边来自多条原边),先把后续 source 用
`elementMapPrefix() << 'K'`(即 `;K`)拼成 `(name1|name2|...)`,再交给 StringHasher
压缩成短 ID(`:1762-1765`):
```cpp
sids.push_back(Hasher->getID(ss.str().c_str()));
ss.str("");
ss << sids.back().toString();   // 例如 "#1b"
postfix = ss.str();
```

最后调用 `encodeElementName` 把 Tag 附上、写入 ElementMap(`:1792-1794`):
```cpp
ensureElementMap()
    ->encodeElementName(element[0], first_name, ss, &sids, Tag, op, first_key.tag);
elementMap()->setElementName(element, first_name, Tag, &sids);
```

#### 阶段 ③ — Reverse + Forward 补齐(`:1800-1990`)

**Reverse pass**(`:1810-1886`):从高级元素(Face)开始,如果 face 命名了但它的 edge
还没名,就用 `upperPostfix() = ";:U"` 派生:
```cpp
ss << upperPostfix();
if (nameInfo.index > 1) ss << nameInfo.index;
```
例:Face 名 `;F1`,它包含的未命名 Edge 会被命名为 `;F1;:U`、`;F1;:U2`、…

**Forward pass**(`:1888-1985`):反过来,从低级元素往高级合并 — 若某个 face 的
**所有 outer wire 边**都有名字,则把这些边名拼成 `(E1|E2|E3)` 哈希后作为 face 名,
用 `lowerPostfix() = ";:L"` 包装。

整个循环会因 `delayed = true` 跑一次,处理 ① 中被推迟的高层映射。

#### 关键不变量
- 阶段 ② 优先使用低层(更精确)映射;阶段 ③ 补齐遗漏。
- 任何已经有名字的元素不会被覆盖 — `if (getMappedName(element)) continue;`
- 所有写入都通过 `setElementName(idx, mapped, Tag, &sids)`,Tag 用来防止跨对象冲突。

### 2.2 `encodeElementName` 细节
`src/App/ElementMap.cpp:620-694`

```cpp
ss << POSTFIX_TAG << std::hex;   // ";:H"
if (tag < 0) ss << '-' << -tag;
else if (tag != 0) ss << tag;
if (pos != 0) ss << ':' << pos;  // 后缀起始偏移
ss << ',' << element_type;       // 'V'/'E'/'F' 之一
```

最终格式:`;:H<hex_tag>:<offset>,<type>` —— 这就是为什么一个完整 mapped name 长
这样:
```
;E1;:G;:H38:2,F
└──┘ └─┘ └──────────┘
源名 GEN  TAG postfix
```

注意 `encodeElementName` 还做了一项重要优化:**避免对同一 Tag 重复编码**
(`:644-668`)— 一个特征的中间步骤产生的 sub-shape 不会无限叠加 Tag。

---

## 3. 操作码字典
`src/Mod/Part/App/TopoShapeOpCode.h`

| 类别 | OpCode 常量 | 字面 |
|---|---|---|
| Boolean | `Fuse` `Cut` `Common` `Section` `Xor` | `FUS` `CUT` `CMN` `SEC` `XOR` |
| Compound | `Compound` `Compsolid` `Shell` `Wire` `Pipe` | `CMP` `CSD` `SHL` `WIR` `PIP` |
| 通用 | `Tag` `Copy` `Transform` `Gtransform` | `TAG` `CPY` `XFM` `GFM` |
| 面构造 | `Face` `FilledFace` `BSplineFace` `HalfSpace` | `FAC` `FFC` `BSF` `HSP` |
| 拉伸/旋转 | `Extrude` `Revolve` `Prism` | `XTR` `RVL` `PSM` |
| 修饰 | `Fillet` `Chamfer` `Draft` `Thicken` `Offset` `Offset2D` | `FLT` `CHF` `DFT` `THK` `OFS` `OFF` |
| Sweep 类 | `Loft` `Sweep` `PipeShell` `ThruSections` | `LFT` `SWP` `PSH` `TRU` |
| 其他 | `GeneralFuse` `Refine` `Boolean` `Slice` `Maker` `Solid` `Sewing` `Mirror` `Sketch` `SketchExport` `Shapebinder` `ShellFill` `RuledSurface` `Split` `Evolve` | `GFS` `RFI` `BOL` `SLC` `MAK` `SLD` `SEW` `MIR` `SKT` `SKE` `BND` `SHF` `RSF` `SPT` `EVO` |

`Version = 15` 是当前编码方案号。**修改任何 op 码或后缀含义都必须 bump 这个版本号**,否则
旧文件加载会导致名字错位。

---

## 4. 特征级流程示例

### 4.1 凸台 / Pad
路径:`PartDesign::Pad::execute → FeatureExtrude::buildExtrusion → ...`

```
FeaturePad.cpp:110-113
  └─ buildExtrusion(MakeFace | MakeFuse)

FeatureExtrude.cpp:323  buildExtrusion()
  ├─ :489+    generateSingleExtrusionSide(sketch, dir, ...)
  │   └─ FeatureExtrude.cpp:834+ → makeElementPrism [:952]
  │                            或 makeElementPrismUntil [:893]
  │
  ├─ :714     prism.makeElementXor(prisms, OpCodes::Extrude)  // 合并多棱柱
  ├─ :741     prism.Tag = -this->getID()                       // ★ 负 Tag = 中间形状
  └─ :754     result.makeElementBoolean("FUS"/"CUT", {base, prism})
              └─ 内部走 makeShapeWithElementMap + MapperMaker
                 → result 中每个面/边都拿到 mapped name
```

**`prism.Tag = -this->getID()` 是关键技巧**:中间棱柱的 Tag 设为负值,产生的元素名里
`;:H-XX` 永远不会和真实对象产生的元素重名,但又能在历史链中标识"属于这个 Pad 的中间产物"。

举例:Sketch 里的边 `E1` 经过 Pad 拉伸后产生侧面,该面的 mapped name 大致是:
```
;E1;:G;:H<base_tag>:<offset>,F
```
保存到 .FCStd 时压成 `#<sid>` 引用(见 §5、§6)。

### 4.2 圆角 / Fillet
路径:`PartDesign::Fillet::execute`

```
FeatureFillet.cpp:77-145  execute()
  ├─ baseShape = getBaseTopoShape()
  ├─ edges = getContinuousEdges(baseShape)
  └─ :119  shape.makeElementFillet(baseShape, edges, R, R)

TopoShapeExpansion.cpp:4083-4113  makeElementFillet()
  ├─ op = OpCodes::Fillet ("FLT")
  ├─ BRepFilletAPI_MakeFillet mkFillet(shape.getShape());
  ├─ for each edge: mkFillet.Add(R, R, edge)
  └─ return makeElementShape(mkFillet, shape, op);
       └─ 内部 → makeShapeWithElementMap(mkFillet.Shape(),
                                          MapperMaker(mkFillet),
                                          {shape}, "FLT")
```

圆角处新产生的圆柱面通常来自一条边的 Generated → 名字形如 `;E5;:G;:H<tag>:0,F`,
后缀 `:G` + op 码 `FLT` 让它和"拉伸的侧面"区分开。

### 4.3 倒角 / Chamfer
`FeatureChamfer.cpp:122-165` → `TopoShapeExpansion.cpp:4115-4180`

与 Fillet 几乎对称,区别仅在 `BRepFilletAPI_MakeChamfer` + `op = "CHF"`。

### 4.4 任意 Boolean
`TopoShapeExpansion.cpp:5811` `makeElementBoolean()` — Fuse/Cut/Common 内部都封装为
`FCBRepAlgoAPI_*` + `MapperMaker`,走同一条 `makeShapeWithElementMap` 路径。

### 4.5 串联多个特征:一个面如何"穿越"特征链
假设:Pad → Fillet → Chamfer

1. **Pad** 阶段:某个侧面命名为 `A = ;E1;:G;:H<pad_tag>:0,F`(`pad_tag` = Pad 的 ID)
2. **Fillet** 阶段:这个侧面未被圆角动到,在新 ElementMap 里通过 `mapSubElement`
   原样继承名字 `A`(对应不同 Face 序号也无妨,反向表自动指向新序号)。
3. **Chamfer** 阶段:同 2,继续继承。

如果 **Fillet 触碰了** `A`,它要么被 Modified(同类型变形)→ 新名 `A;:M;:H<fil_tag>:..,F`,
要么被 Generated(分裂)→ 新名 `A;:G;:H<fil_tag>:..,F`。**原始 source name `A` 始终保留
在 postfix 链里**,所以一直能反查到"这是从 Pad 的某条边拉伸出来的那个面"。

---

## 5. StringHasher — 名字压缩

`src/App/StringHasher.h:55-120`,实现 `src/App/StringHasher.cpp`

随着特征链增长,mapped name 会越来越长(链式后缀)。StringHasher 通过两种手段控制
膨胀:

1. **引用计数**:用 `QByteArray` 存储,长字符串共享同一段内存。
2. **整数引用**:把长 name 哈希成 `#<hex_id>` 引用另一个 StringID。

阈值控制 — `StringHasher.cpp:268`:
```cpp
bool hashed = hashable && _hashes->Threshold > 0
              && (int)data.size() > _hashes->Threshold;
```
超过阈值的字符串用 SHA1 算 20 字节摘要:
```cpp
QCryptographicHash hasher(QCryptographicHash::Sha1);
hasher.addData(data);
dataID._data = hasher.result();    // 二进制 hash
```

`StringID::Flags` 描述结构(`StringHasher.h:82-110`):
- `Hashed` — `_data` 是 sha1 摘要而非原文
- `Postfixed` — 拆分为前缀 + 后缀
- `PostfixEncoded` — 后缀本身是 `#<id>` 引用
- `Indexed` — 前缀是 `text + 整数 index`(如 `Edge` + `1`)
- `PrefixID` / `PrefixIDIndex` — 前缀整体或文本部分用另一个 StringID 引用

每个 Document 共享一个 `StringHasher`(`FeatureExtrude.cpp:703` 可以看到
`getDocument()->getStringHasher()`),保证跨特征的名字能复用 ID 表。

---

## 6. 持久化

### 6.1 顶层 XML 结构
`src/App/ComplexGeoData.cpp:457-529`

`ComplexGeoData::Save` 写出两段 XML:
```xml
<ElementMap new="1" count="1">    <!-- 占位,触发旧版重算 -->
  <Element key="Dummy" value="Dummy"/>
</ElementMap>
<ElementMap2 count="N">           <!-- 新格式 -->
  ...binary stream...
</ElementMap2>
```
若 element map 很大(`_persistenceName` 非空),写成外部 `.txt` 附件:
```xml
<ElementMap2 file="ElementMap_xxxx.txt"/>
```

### 6.2 ElementMap 二进制流
`src/App/ElementMap.cpp:108-200`(`save`),`:71-106`(`beforeSave` 标记 sid)

简化格式:
```
ElementMap <map_index> <dedup_id> <num_indexed_names>

<IndexedName_string_1>

ChildCount <n>
  <child_idx> <offset> <count> <tag> <map_index> <postfix> 0.<sid>.<sid>...

NameCount <m>
  :<postfix_idx>.<element_idx>      ← IndexedName 形式 (text 已索引)
  $<hashed_bytes>                   ← StringID 引用
  ;<raw_bytes> .<postfix_id>        ← 原始字节
  ...
```

三种 name 编码(`:160-191`):
- 形如 `Edge1` → `:<postfix_idx>.<index>`(后缀 "Edge" 已在 `postfixMap` 里)
- 已经哈希到 StringHasher → `$<bytes>`
- 都不是 → `;<raw>` 原样写入

`ChildCount` 段记录跨 ElementMap 的引用 — 父 map 的某段名字范围由子 map 提供。
子 map 用 `dedup_id`/`mapIndex` 表示,**同一子 map 多次引用只存一次**。

### 6.3 Restore
`ComplexGeoData.cpp:484-529` + `ElementMap::restore`(`ElementMap.cpp` 内,与 save
对称)。

- 若 XML 是旧版 `<ElementMap>` 含 `Dummy` 占位,跳过,等待重算
- 若是 `<ElementMap2 file="...">`,读外部附件
- 否则按二进制流恢复 — 每个 `$<bytes>` 通过当前 Hasher 反查 StringID,链式
  解开 `#<hex>` 引用

---

## 7. 回读路径:用户引用如何被解析

下游 Sketch 引用 `Pad001.Face3`,保存时**不会**写 `Face3`,而是写它当前对应的 mapped
name + `#<hash>`。重新计算后:

`ComplexGeoData::getElementName` — `src/App/ComplexGeoData.cpp:273-299`

```cpp
MappedElement getElementName(const char* name, ElementIDRefs* sid, bool copy) const
{
    IndexedName element(name, getElementTypes());   // 试解析 "Face3"
    if (element) {
        return {getMappedName(element, false, sid), element};
    }
    // 否则 name 是 mapped 形式,反查它现在指向哪个 Face
    const char* mapped = isMappedElement(name);
    if (mapped) name = mapped;

    const char* dot = strchr(name, '.');
    MappedName result_name = MappedName(name, static_cast<int>(dot - name));
    result.index = getIndexedName(result_name, sid);
    return result;
}
```

两个方向:
- **正向**:`Face3 → ;E1;:G;:H38:0,F`(保存时调用)
- **反向**:`;E1;:G;:H38:0,F → Face7`(重算后,序号可能变了)

**这就是"一个面在做了别的特征后还能唯一标识自己"的最终机制**:身份不再是 OCC 序号,
而是历史编码的 mapped name;ElementMap 的反向表负责把它解析回当前序号。

---

## 8. 文件总览

| 文件 | 作用 | 行数 |
|---|---|---|
| `src/App/ElementNamingUtils.h/.cpp` | 编码字典 + 字符串工具 | 127 + 143 |
| `src/App/MappedName.h/.cpp` | MappedName 类型 | 1247 + 254 |
| `src/App/MappedElement.h/.cpp` | MappedName + IndexedName 配对 | 150 + 269 |
| `src/App/ElementMap.h/.cpp` | 双向表 + 编码/持久化 | 424 + 1484 |
| `src/App/ComplexGeoData.h/.cpp` | 基类、Tag、Save/Restore | 763 + 748 |
| `src/App/StringHasher.h/.cpp` | 字符串哈希 / 整数引用表 | — |
| `src/Mod/Part/App/TopoShapeOpCode.h` | 操作码常量 + Version | 104 |
| `src/Mod/Part/App/TopoShape.h` | TopoShape 类、Mapper 基类、各种 Mapper* | 3055 |
| `src/Mod/Part/App/TopoShapeExpansion.cpp` | `makeShapeWithElementMap` + 全部 `makeElement*` | 6151 |
| `src/Mod/Part/App/TopoShapeCache.h/.cpp` | 每个 TopoShape 的祖先索引缓存 | 145 + 258 |
| `src/Mod/Part/App/TopoShapeMapper.h/.cpp` | 通用 ShapeMapper(modified/generated 词典) | 312 + 202 |
| `src/Mod/PartDesign/App/FeatureExtrude.cpp` | Pad/Pocket 通用流程 | 1014 |
| `src/Mod/PartDesign/App/FeaturePad.cpp` | Pad 入口 | 113 |
| `src/Mod/PartDesign/App/FeatureFillet.cpp` | Fillet 入口 | — |
| `src/Mod/PartDesign/App/FeatureChamfer.cpp` | Chamfer 入口 | — |

---

## 9. 推荐阅读顺序

1. `ElementNamingUtils.h` —— **15 分钟**,看完就懂 mapped name 字面含义
2. `TopoShapeOpCode.h` —— **5 分钟**,操作码一览
3. `MappedElement.h` + `MappedName.h` 的类声明 —— 数据结构
4. `ElementMap.h` —— 双向表 API
5. `FeaturePad.cpp` + `FeatureExtrude.cpp:323-800` —— 真实端到端示例
6. **`TopoShapeExpansion.cpp:1408-1992`**(`makeShapeWithElementMap`)—— 核心算法
7. `ElementMap.cpp:108-200` + `ComplexGeoData.cpp:457-529` —— 持久化细节
8. `StringHasher.h/.cpp` —— 想搞懂 `#xxxx` 引用怎么压缩时再看

---

## 10. 修改时的注意事项

- **改动 mapped name 编码方式必须 bump `OpCodes::Version`**(`TopoShapeOpCode.h:49`),
  否则旧 .FCStd 加载会出现 silent 错位。
- **不要绕过 `makeShapeWithElementMap` 直接 `setShape`** — 那会丢失 element map。
  哪怕你只是想换个 OCC API,也应当包一个 `Mapper` 子类。
- **中间形状的 Tag 用负值**(参考 `FeatureExtrude.cpp:741`),保证不与真实对象冲突。
- **测试 toponaming 稳定性**的最小回归:Pad → 改长度 → Pad → 改草图边数 → 引用是否
  自动跟踪。FreeCAD 单元测试目录 `tests/src/Mod/Part/` 下有相关用例。

---

## 11. 实例图解:一个面如何在特征链中继承身份

> 本节用一个最小可视化例子,把 §1–§3 的抽象概念落到具体名字上。
> 场景:一个 10×6 矩形草图 → Pad 拉伸 5mm → Fillet 前底边。
> Tag 假定:Sketch = 10、Pad = 20(hex `14`)、Fillet = 30(hex `1e`)。

### 阶段 ⓪ — 草图

平面矩形,4 条边:

```
                Edge1 (上)
            ┌────────────────┐
            │                │
    Edge4   │   FaceSketch   │   Edge2
   (左)     │                │  (右)
            └────────────────┘
                Edge3 (下)
```

Sketch 输出的 wire 经 `FaceMakerCheese` 包成 face。此时 element map(简化展示,实际
名字会带 sketch 内部 geometry ID,这里用 `g1`-`g4` 示意):

| IndexedName | MappedName | 含义 |
|---|---|---|
| Edge1 | `;g1` | 顶边 |
| Edge2 | `;g2` | 右边 |
| Edge3 | `;g3` | 底边 |
| Edge4 | `;g4` | 左边 |
| Face1 | `;f0` | 草图面 |

### 阶段 ① — Pad 拉伸 5mm

调用链:`Pad::execute → FeatureExtrude::buildExtrusion → makeElementPrism →
makeShapeWithElementMap(MapperMaker, sketchshape, "XTR")`。

OCC 的 `BRepPrimAPI_MakePrism` 给 mapper 报告的历史:

```
sketch FaceSketch  ──Modified──►  底面
                   ──Generated──►  顶面
sketch Edge1       ──Generated──►  后侧面    (E1 扫掠出来)
sketch Edge2       ──Generated──►  右侧面
sketch Edge3       ──Generated──►  前侧面
sketch Edge4       ──Generated──►  左侧面
sketch Vertex_n    ──Generated──►  4 条立柱边
sketch Edge_n      ──Modified──►   底/顶面上的水平边
```

`makeShapeWithElementMap` 把这些史料按"源名 + 后缀 + Tag"编码:

```
                              Face_top ← g0;:G;:H14,F     (sketch面 Generated)
                          ┌─────────────┐
                         ╱│            ╱│
                        ╱ │           ╱ │
                       ╱  │          ╱  │ ← Face_back ← g1;:G;:H14,F
                      ╱   │         ╱   │     (Edge1 Generated)
            Face_left ┌─────────────┐    │
            g4;:G;:H14,F │            │    │
                      │   │            │   │ ← Face_right ← g2;:G;:H14,F
                      │   └────────────│───┘
                      │  ╱             │  ╱
                      │ ╱   Face_front │ ╱
                      │╱   g3;:G;:H14,F│╱
                      └────────────────┘
                              Face_bot ← g0;:M;:H14,F      (sketch面 Modified)
```

完整 element map(IndexedName 由 OCC 排序决定,这里只是示意编号):

| IndexedName | MappedName | 解读 |
|---|---|---|
| Face1 | `g0;:M;:H14,F` | 底面 = 草图面被修改 |
| Face2 | `g0;:G;:H14,F` | 顶面 = 草图面被生成 |
| Face3 | `g3;:G;:H14,F` | 前侧 = Edge3 生成 |
| Face4 | `g2;:G;:H14,F` | 右侧 = Edge2 生成 |
| Face5 | `g1;:G;:H14,F` | 后侧 = Edge1 生成 |
| Face6 | `g4;:G;:H14,F` | 左侧 = Edge4 生成 |
| Edge9 | `g3;:M;:H14,E` | 底/前交界边 = Edge3 修改后投到底面 |
| ... | ... | ... |

**关键看一个名字怎么读** —— `g3;:G;:H14,F`:

```
  g3      ; :G    ; :H 14    , F
  │        │       │  │       │
  源名     生成    Tag 0x14   类型 Face
  (Edge3) (Generated) (=20, Pad)
```

### 阶段 ② — Fillet 前底边(Face_bot ↔ Face_front 的交界)

调用链:`Fillet::execute → makeElementFillet → makeElementShape →
makeShapeWithElementMap(MapperMaker(BRepFilletAPI_MakeFillet), padshape, "FLT")`。

OCC 报告:

```
被选中的那条边  ──Generated──►  新圆柱面 (Face_fillet)
Face_bot       ──Modified──►   稍微变小的底面
Face_front     ──Modified──►   稍微变小的前侧
其他 4 个面    ──没动──►       通过 mapSubElement 直接继承(不加后缀)
```

新的 element map(`H1e` = Tag 30):

```
                          ┌─────────────┐
                         ╱│            ╱│
                        ╱ │ Face_top  ╱ │
                       ╱  │ (继承不变) ╱  │
                      ┌─────────────┐    │   ← 其他面: 名字 100% 继承
                      │             │    │
                      │             │    │
                      │             │    │
                      │  ╱      ┌───────────────┐
                      │ ╱    ╔══│ Face_fillet   │  ← 新圆柱面
                      │╱     ║  │ 边名;:G;:H1e,F│      = 被填的边 Generated
                      └──────╝  └───────────────┘
                      Face_bot                     Face_front
                      g0;:M;:H14,F;:M;:H1e,F       g3;:G;:H14,F;:M;:H1e,F
                      ↑                            ↑
                      被 Pad 修改过,又被 Fillet 修改  被 Pad 生成,被 Fillet 修改
```

| IndexedName | MappedName | 解读 |
|---|---|---|
| Face1 | `g0;:M;:H14,F` | 顶面 — 完全继承(没被 fillet 动到) |
| Face2 | `g0;:G;:H14,F` | 也是没动的某个面 — 完全继承 |
| Face3 | `g0;:M;:H14,F;:M;:H1e,F` | **底面 — 在 Pad 后缀末再追加 Fillet 的 `;:M;:H1e,F`** |
| Face4 | `g3;:G;:H14,F;:M;:H1e,F` | **前侧 — 同样链式追加** |
| Face5 | `g1;:G;:H14,F` | 后侧 — 没动,继承 |
| Face6 | `g2;:G;:H14,F` | 右侧 — 没动,继承 |
| Face7 | `g4;:G;:H14,F` | 左侧 — 没动,继承 |
| Face8 | `<被填边的源名>;:G;:H1e,F` | **NEW** 圆柱面 — 由那条边生成 |

注意 OCC 在 Fillet 之后会重新排列面序号,**所以"前侧面"这次可能是 Face4 而不是
Face3**。但它的 mapped name 仍然以 `g3;:G;:H14,F` 开头 —— **物理意义没变**。

### 关键洞察:身份继承的三种模式

通过这个例子,可以看出三种继承模式:

**1. 不变继承(`mapSubElement`)** — 一个面在新操作中没被触碰,它的 mapped name
**原样照搬**到新形状的 element map,不加任何后缀。Face_top 在 Fillet 阶段就是这样。

**2. Modified 链式追加** — 同类型变形(面→面、边→边),在原 mapped name 后追加
`;:M;:H<新Tag>,<类型>`。Face_bot 在 Fillet 后变成 `g0;:M;:H14,F;:M;:H1e,F` —— 你能
顺着名字一路读出:**"草图面 → Pad 修改 → Fillet 又修改"**。

**3. Generated 派生** — 跨类型派生(边→面、点→边),用 `;:G`。新圆柱面就是这样从
被填的那条边派生出来。

### 反查路径:用户引用 "Pad 的前侧面" 时

假设用户在 Pad 之后选了 `Face3`,FreeCAD 保存到 .FCStd 里的不是 `Face3`,而是
**当时的 mapped name** `g3;:G;:H14,F#xxxxxx`(`#xxxxxx` 是 StringHasher 压缩后的引用)。

后来加了 Fillet,前侧面的 IndexedName 变成 `Face4`,但 ElementMap 反向表里
`g3;:G;:H14,F` 这一项(连同它在 Fillet 阶段追加 `;:M;:H1e,F` 后的新版本)都指向当前的
`Face4`。

`ComplexGeoData::getElementName` 一查就能找回 —— **这就是"凸台之后做了别的特征,
还能唯一标识这个面"的最终实现**。

### 用图概括整个传播过程

```
草图阶段                   Pad 阶段                            Fillet 阶段
─────────                  ─────────                           ───────────

Edge3 (;g3)  ─Generated─►  Face_front (g3;:G;:H14,F) ─Modified─► Face_front'
                                                                  (g3;:G;:H14,F;:M;:H1e,F)

Edge3 ─────────────────────────────同时─────────────────Generated─►  Face_fillet
                                                                  (<边名>;:G;:H1e,F)
                                                                  ↑
                                                                  圆柱面里包含 g3 的痕迹

Face_top  ─Generated/不变─► Face_top  ──────────不变继承──────────► Face_top
          (g0;:G;:H14,F)              (g0;:G;:H14,F)
```

**Mapped name 是一条"血缘"** —— 每次特征执行只是在末尾追加一段后缀,**永远不丢失
祖先信息**。这就是 toponaming 比"记录序号"高明的地方:即使 OCC 在 Fillet 后把面重
排成完全不同的顺序,只要 mapped name 链没断,引用就能跟着走。

---

*文档作者:基于 realthunder (Zheng Lei) 提交的 Toponaming v15 方案整理。*
*最后核对:本仓库 main 分支 HEAD。*
