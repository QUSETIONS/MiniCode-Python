# 工程结构操作纲领

本文定义本仓库的工程目录、模块边界、源码组织、跨模块依赖、脚本调用、测试镜像、供应封装、扫描诊断和验证规则。本文件以可执行、可扫描、可审计、可验证为口径；当它与 Node、PHP、前端、后端、CLI、测试框架或其他生态的惯用目录冲突时，以本文为准。

本文优先使用主流工程词汇，但不以迎合惯例为目标。命名必须服务于语义精确。目录和文件只有处在本文定义的位置时才具有结构语义。

本文件以书名号包裹章节标题，交叉引用同一规则的唯一权威定义处；同一事实只在其权威章节完整陈述一次，其余位置只引用、不复述。引用必须解析到真实在场的章节。

## 团队架构

### 指挥链

```text
指挥官 (Commander)          <- 战略目标、方案审批、最终决策
        |
        v
副官 (Adjutant)             <- 接令、拆解、开 Workflow、综合战报
        |
        v
士官 (Sergeant)             <- 专项负责：侦察、实现、审查、测试、迁移
        |
        v
codex 士兵 (Codex Soldier)  <- 实际读写文件、执行命令、搜索、验证
```

### 协作铁律

- 所有读写操作都必须有明确目标、路径、预期结果和验证方式。
- 不允许用模糊意图驱动文件改写。
- 不允许为通过检查引入 `stub`、`mock`、`skip`、绕过、假通过或逃逸口。
- 不允许把巨型文件按行数、体积或随机边界切片冒充拆分；拆分必须按语义职责。
- Main 模块之间禁止直接构成性依赖；共用能力必须沉淀到 Package 模块。
- 符号链接不能表达结构正确性，不能作为结构载体依赖。
- 除非明确要求，不删除运行时数据库卷，不重写运行时数据。
- 除非明确要求，不使用 `git reset --hard`、`git checkout --` 等破坏性 Git 命令。
- 工作区不是独占的。大范围编辑前先看当前文件状态；不要还原自己没有做的改动；遇到并发改动时，顺着当前状态继续做。

## 核心模型

结构模型只有三个核心对象：

```text
Workspace -> project -> Module
```

- 工作区是项目集合边界。
- 项目是模块集合和内嵌工作区集合边界。
- 模块只存在于项目的模块角色空间下。
- 项目没有固有名；项目目录名就是项目实例名。
- 模块表面是模块进入结构依赖图或被平台运行的公开入口。
- 只有拥有非空公开表面的合法模块才拥有模块表面、才可能成为可依赖模块（判据见《可依赖模块与依赖图》）。
- 模块公开表面就是结构本身：由 `Application` 的公开契约子节（`Port/In`、`Entry`、`Command`、`Query`、`Result`、`Dto`、`Error`）与 `Src/Boot/**`（模块自组合得到的可运行成品，若存在）共同构成；`Port/Out` 是模块内自接缝，不属于公开表面。
- `Src/Import/` 只形成当前模块的跨模块结构依赖边和本地绑定，不属于当前模块对外公开表面。

本文件保留两种扫描 profile：

| profile | 输入根语义 | 扫描起点 |
| --- | --- | --- |
| 外层工作区 profile | 输入根是产品工作区根 | 输入根直接子项是产品项目 |
| 产品项目根 profile | 输入根本身是一个产品项目实例 | 从项目扫描阶段开始 |

当前仓库必须使用产品项目根 profile。输入根必须是真实目录，不能是符号链接。扫描器不读取输入根 basename 的结构语义，不把输入根 basename 作为项目名，不对输入根 basename 应用结构路径段、保留名或大小写规则。

产品项目根 profile 的根项目在诊断 payload 中使用稳定标识：

```text
@rootProject
```

- 根项目没有项目名。
- 根项目不参与结构路径段唯一性集合。
- 根项目不进入 canonical Import stem。
- 根项目默认不受 Vendor 支配。
- 只有从根项目向下经过 `Vendor/` 工作区后，后代项目才进入 Vendor 支配。
- 根项目下的 `Main/` 与 `Package/` 属于同一项目。
- 根项目内嵌 `Tool/`、`Script/`、`Docs/` 工作区下的项目不与根项目互为 same project。

产品项目根 profile 的根目录闭合先排除固定过程载体：

```text
.git/
.temp/
CLAUDE.md
```

排除项不作为自由余项参与结构投影，不进入产品项目结构闭合。工具运行产生的状态、记录和报告（即开放式过程载体——区别于上列固定过程载体）必须进入合法模块的 `Data/` 目录，不在根目录新增；根目录意外出现的此类文件结构上按自由余项处理，本约束是对工具产出位置的规范，不另立结构诊断。

结构目录默认按需出现。后续规则显式要求出现时除外。结构目录一旦出现，就必须满足自身内容规则。空目录是结构违规；适用于结构目录、自由余项目录、`Config/` 内部目录、`Data/` 内部目录和 `Bin/`。

## 工作区

工程结构承认五个工作区固有名：

| 名称 | 含义 | 合法位置 |
| --- | --- | --- |
| `Workspace` | 产品工作区模型名 | 仅扫描输入根 |
| `Tool` | 工具工作区 | 项目或模块的直接子项 |
| `Script` | 脚本工作区 | 项目或模块的直接子项 |
| `Docs` | 文档工作区 | 项目或模块的直接子项 |
| `Vendor` | 供应工作区 | 模块的直接子项 |

本表是工作区固有名合法位置的权威定义。`Vendor` 只在模块直接子项位置合法，因此项目直接子项 `Vendor` 永远违规（机制见《名称、保留名与载体》保留名身份段）。

规则：

- `Workspace` 不能出现在任何项目或模块的直接子项位置。
- `Tool` 工作区下的项目辅助它所在的项目或模块，承载开发工具、扫描器、迁移器、生成器和自动化建设过程。
- `Script` 工作区下的项目表达平台特化的直接执行入口。脚本只调用其目标模块的运行表面与公开契约，不成为目标模块 `Src` 的一部分（调用口径见《脚本调用边界》）。
- `Docs` 工作区下的项目是开发者运行的文档项目，承载文档化、推理、建设说明生成、工程约定维护和文档结果。
- `Vendor` 工作区下的项目（即供应项目）表达它所在模块引入的外部构成能力。
- 工作区目录下的直接子项全部是项目目录；不放模块、文件、符号链接或自由余项。
- 工作区一旦出现，必须至少包含一个合法定位的项目目录。
- 工作区直接子项中的非法项产生工作区闭合错误，但不取消同一工作区下其他合法定位项目的结构身份（身份与闭合分离原则见《扫描阶段与识别顺序》）。

示例：

```text
<workspace_root>/
  <project_alpha>/

<project_or_module>/
  Tool/<project_beta>/
  Script/<project_gamma>/
  Docs/<project_delta>/

<module>/
  Vendor/<project_epsilon>/
```

## 项目

项目语义由所在工作区决定：

| 所在工作区 | 项目类型 |
| --- | --- |
| 产品 `Workspace` 输入根 | 产品项目 |
| `Tool/` | 工具项目 |
| `Script/` | 脚本项目 |
| `Docs/` | 文档项目 |
| `Vendor/` | 供应项目 |

项目目录下只能出现模块角色空间、内嵌工作区和自由余项：

```text
<project>/
  Main/
  Package/
  Tool/
  Script/
  Docs/
  <free_remainder>
```

规则：

- `Main/` 与 `Package/` 只在项目直接子项位置具有模块角色空间语义。
- `Main/` 的直接子目录是 Main 模块。
- `Package/` 的直接子目录是 Package 模块。
- `Main/` 与 `Package/` 按需出现；一旦出现，必须至少包含一个合法定位的模块目录，并且只能放模块目录。
- 模块角色空间直接子项中的非法项产生角色空间闭合错误，但不取消同一角色空间下其他合法定位模块的结构身份。
- `Tool/`、`Script/`、`Docs/` 只在项目或模块直接子项位置具有内嵌工作区语义；`Vendor/` 只在模块直接子项位置具有内嵌工作区语义（见《工作区》表）。
- 项目直接保留名是 `Main`、`Package`、`Tool`、`Script`、`Docs`、`Vendor`、`Workspace`。
- 保留名优先于自由余项。保留名一旦出现，就必须满足对应结构语义。
- 项目直接子项 `Workspace` 与 `Vendor` 永远违规。
- 项目直接子项位置的其他名称是自由余项。
- 项目目录一旦出现，必须至少包含一个直接子项。
- 项目可以只包含自由余项；这种项目仍是合法项目实例，但其可运行、辅助、文档化或供应封装能力只有在出现对应模块表面后成立。
- 自由余项可以是普通文件或普通目录；自由余项内部不递归产生工作区、项目、模块或模块保留项语义。

## 模块

模块只存在于：

```text
<project>/Main/<module>/
<project>/Package/<module>/
```

模块目录下只能出现模块保留项、内嵌工作区和自由余项：

```text
<module>/
  Src/
  Test/
  Config/
  Data/
  Bin/
  Tool/
  Script/
  Docs/
  Vendor/
  <free_remainder>
```

### 模块保留项

| 名称 | 语义 |
| --- | --- |
| `Src/` | 模块能力的定义与实现 |
| `Test/` | 模块 `Src/` 的镜像测试过程 |
| `Config/` | `Src/` 过程的不变量、稳定前提、约束、策略、参数和规则材料 |
| `Data/` | 模块数据、过程产物、推理结果、样本、快照、报告和测试数据 |
| `Bin/` | 已生成、引入或交付并被视为二进制载体的普通文件 |
| `Tool/` | 绑定当前模块的工具工作区 |
| `Script/` | 绑定当前模块的脚本工作区 |
| `Docs/` | 绑定当前模块的文档工作区 |
| `Vendor/` | 绑定当前模块的供应工作区 |

规则：

- `Data/Test/` 是测试数据保留位置。测试数据进入 `Data/Test/`；测试过程进入 `Test/`。
- 只有 `Data/` 的直接子项 `Test` 具有测试数据结构语义，且必须是普通目录。
- `Bin/` 只承载普通文件；不承载脚本项目、工具项目、源码过程、测试过程或第三方本体目录。
- 本表按模块直接保留名分组，但二者分属不同结构实体类别：`Src`、`Test`、`Config`、`Data`、`Bin` 是模块保留项本体（`entityKind` 为模块保留项），`Tool`、`Script`、`Docs`、`Vendor` 是绑定当前模块的内嵌工作区（`entityKind` 为内嵌工作区，识别口径见《扫描阶段与识别顺序》模块识别），故同名目录在 payload 中按其所属类别唯一归类，不二义。
- 模块直接保留名是 `Src`、`Test`、`Config`、`Data`、`Bin`、`Tool`、`Script`、`Docs`、`Vendor`、`Workspace`。
- 保留名优先于自由余项。
- 模块直接子项 `Workspace` 永远违规。
- 模块直接子项位置的其他名称是自由余项。
- 模块目录一旦出现，必须至少包含一个直接子项。
- 模块可以只包含自由余项。

`Src/`、`Test/`、`Config/`、`Data/`、`Bin/` 各保留项的内部规则分别见《源码结构总则》及其后各 Src 区域章、《测试结构》、《Config、Data 与 Bin》。

内嵌工作区只绑定它的直接父级结构实体。例如：

```text
<project_alpha>/Tool/<project_beta>/Main/<module_beta>/Vendor/
```

该 `Vendor/` 是绑定模块 `<module_beta>` 的供应工作区，不是绑定工具项目 `<project_beta>` 或外层项目 `<project_alpha>` 的供应工作区。这个规则允许反复嵌套，并避免跨层继承所在对象。

## 模块角色

Main 模块和 Package 模块使用完全相同的模块内部架构（见《源码结构总则》及其后各 Src 区域章）。二者差异只体现在跨模块依赖口径和产品语义，不体现在 `Src/` 内部结构。两类模块的跨模块构成性依赖口径由《可依赖模块与依赖图》权威定义，本节只陈述角色语义并前向引用该处。

### Main 模块

Main 模块表达产品级可运行/可部署成品、操作入口能力或面向外部运行边界的应用契约。Main 模块的公开表面 = `Application` 公开契约 ∪ `Src/Boot` 运行表面：它经 `Src/Boot` 的 `createApp(env)` 自组合成可运行成品，由绑定的 `Script/` 工作区与平台运行边界消费；脚本调用口径见《脚本调用边界》。

Main 模块的跨模块构成性依赖口径由《可依赖模块与依赖图·Main 依赖规则》权威给出。要点：Main 只依赖同项目 Package，永不直接依赖 Main（Main 到 Main 不构成依赖图边，只通过运行边界、协议、配置、工具操作或外部系统交互），需要供应能力时先由同项目 Package 表达供应依赖再由 Main 依赖该 Package。

### Package 模块

Package 模块表达可被依赖的构成材料。Package 模块对其他模块只表达构成性依赖，不表达运行交互、操作调用或部署关系。

Package 模块的跨模块构成性依赖口径由《可依赖模块与依赖图·Package 依赖规则》权威给出（含同项目 Package、本模块 `Vendor/` 供应模块、Vendor 支配限制、祖先模块限制）。同一模块对同一目标模块最多对应一个 Import 文件，这条约束由《Import 边界与文件编码》的重复 Import 检查强制。

## 名称、保留名与载体

结构路径段是会被结构规则读取的目录名或源码 stem，包括项目名、模块名、源码目录名、源码文件 stem、Import 编码中的下行路径片段。完整 Import 编码 stem 不是结构路径段；它有自己的编码文法，并按完整 stem 参与同目录唯一性检查。

结构路径段文法：

```text
[A-Za-z][A-Za-z0-9_]*
```

规则：

- 结构路径段大小写敏感。
- ASCII 大小写折叠只处理 `A-Z` 到 `a-z`。
- 不执行 Unicode casefold。
- 不执行 Unicode normalization。
- 不读取平台文件系统大小写规则。
- 结构路径段不使用 `-`，因为 `-` 是 Import 编码中的路径段分隔符。
- 结构路径段不使用 `.`，因为 `.` 用来分隔文件扩展名和测试文件后缀。
- 自由余项不是结构路径段；自由余项名称只受真实文件系统和载体验证约束。

保留名按位置定义：

| 位置 | 保留名或模式 |
| --- | --- |
| 工作区模型名 | `Workspace` |
| 项目直接子项 | `Main`、`Package`、`Tool`、`Script`、`Docs`、`Vendor`、`Workspace` |
| 模块直接子项 | `Src`、`Test`、`Config`、`Data`、`Bin`、`Tool`、`Script`、`Docs`、`Vendor`、`Workspace` |
| `Src/` 直接子项 | `Boot`、`Import`、`Domain`、`Application`、`Adapter` |
| `Data/` 直接子项 | `Test` |

保留名身份与合法位置是两件事，这是判定保留名行为的权威机制：某名称在某位置是保留名，表示它一旦出现就只能按该保留语义解释、不能降级为自由余项；该位置是否还合法，由对应章节判定。`Vendor` 在项目直接子项位置是保留名，因此项目下名为 `Vendor` 的目录只能按供应工作区语义解释、不能当自由余项，而供应工作区只在模块直接子项位置合法（见《工作区》表），故项目直接子项 `Vendor` 永远违规。`Workspace` 在项目和模块直接子项位置同理：是保留名，且永远违规。

`Main` 与 `Boot` 是处在两个不相交位置的保留名，不互相干扰：`Main` 在项目直接子项位置是模块角色空间（其直接子目录是 Main 模块），`Boot` 在模块 `Src/` 直接子项位置是组合根源码区域。模块直接子项位置出现名为 `Main` 的目录，不是角色空间也不是组合根，按自由余项处理；`Src/` 直接子项位置出现名为 `Boot` 的目录才是组合根。

保留名只接受规范 PascalCase 拼写。结构位置上的条目如果按 ASCII 折叠后等于保留名，但原始名称不是规范 PascalCase 拼写，必须判定结构违规。条目如果等于规范保留名，但载体类型不是该保留名要求的普通目录或普通文件，也必须判定结构违规。

项目名和模块名不能使用模型保留词及其 ASCII 大小写变体：

```text
Workspace Tool Script Docs Vendor Main Package Src Test Config Data Bin Import Domain Application Adapter Boot
```

源码目录名和源码文件 stem 只有在 `Boot/`、`Domain/`、`Application/`、`Adapter/` 的后代源码结构内部才可以使用保留名；在那里它们按源码对象解释，不按工作区、项目或模块保留项解释。这个自由不适用于 `Src/` 直接子项。

结构位置要求普通目录或普通文件。普通目录和普通文件排除符号链接、设备、socket、FIFO 和其他特殊文件。扫描器读取时不得跟随符号链接。符号链接不能作为输入根、工作区、项目、模块、模块角色空间、模块保留项、源码文件、测试文件、`Config/` 内容、`Data/` 内容、`Bin/` 内容或自由余项内容。

## 自由余项与载体验证

自由余项不递归识别为工程结构，但必须做载体验证。

规则：

- 项目或模块直接子项位置的自由余项根节点可以是点名，可以是普通文件或普通目录。
- 自由余项根可以与其他自由余项发生 ASCII 大小写折叠重复。
- 只要自由余项根名称按 ASCII 折叠后不等于当前位置保留名，就不触发工作区、项目、模块或模块保留项语义。
- 供应模块直接自由余项目录按结构位置分类为第三方本体目录；这个分类不启动递归结构识别。
- 自由余项内部的 `Workspace` 只是普通名称。
- 点文件、点目录、保留名、保留名大小写变体、大小写折叠重复的普通名称都允许作为自由余项内部的普通名称。

载体验证只检查文件系统载体性质：

```text
普通文件
普通目录
非空目录
禁止符号链接
禁止特殊文件
```

载体验证不检查名称文法、不检查保留名、不检查大小写重复、不检查点名。自由余项目录根及其后代目录都不得为空。自由余项只按每级目录非空做验证，不设置递归普通文件数量目标。无法读取目录、权限错误、遍历错误、目录循环都判定为载体验证失败。

## 大小写与唯一性

同一目录下的结构路径段按大小写敏感比较必须唯一，按 ASCII 大小写折叠比较也必须唯一。唯一性集合同时包含结构子目录名和结构文件 stem。

规则：

- `Src/` 直接层的唯一性集合是五个固定保留目录名 `Boot`、`Import`、`Domain`、`Application`、`Adapter`；该层没有自由命名成员，冲突只表现为保留名大小写变体违规或大小写折叠重复。
- `Src/Import/` 中，Import 编码 stem 按完整 stem 执行唯一性检查。
- 测试镜像使用去掉固定 `.Test.<ext>` 后的 `<mirrored_source_stem>` 参与唯一性检查；该 stem 必须与源码 stem 完全一致。
- 唯一性适用于产品工作区项目名、内嵌工作区项目名、模块角色空间模块名、源码目录名、源码文件 stem、Import 编码 stem、测试镜像 stem。
- 自由余项、`Config/` 内部、`Data/` 内部不进入结构路径段唯一性集合。

唯一性冲突的全部成员都保留候选诊断身份，但都不能成为合法结构节点或合法结构文件。

- 项目名冲突：冲突项目都是非法项目候选，不继续扫描后代。
- 模块名冲突：冲突模块都是非法模块候选，不成为合法模块，不进入可依赖模块集合，不继续扫描后代。
- 源码目录名或源码文件 stem 冲突：冲突成员都是非法源码候选；冲突目录不继续扫描后代，冲突文件不进入结构源码文件集合和测试镜像期望集合。
- Import 编码 stem 冲突：冲突 Import 普通文件都累计 Import stem 唯一性错误，不参与路径反解、canonical 检查、重复 Import 检查、依赖检查、结构源码文件集合或测试镜像期望集合。
- 测试镜像 stem 冲突：冲突测试文件都不能成为合法镜像测试文件。
- 唯一性冲突同时使直接父结构产生闭合错误。

## 源码结构总则

`Src/` 是严格结构化的模块能力集合。所有项目类型中的所有模块都使用同一套 `Src` 内部架构；Main、Package、Tool、Script、Docs、Vendor 项目中的模块都不例外。模块没有源码能力时可以没有 `Src/`。

`Src/` 直接子项只允许五个区域目录，不允许任何普通文件直接位于 `Src/`：

```text
Src/
  Boot/
  Import/
    <encoded_relative_module_path>.<ext>
  Domain/
  Application/
  Adapter/
```

语义：

| 名称 | 语义 |
| --- | --- |
| `Boot/` | 组合根：把 Usecase（及具体 Adapter，若有）组合成可运行成品 `createApp(env) -> RunnableApp` |
| `Import/` | 外部模块表面的本地纯绑定文件集合 |
| `Domain/` | 本模块业务事实、业务规则、领域对象和纯业务关系 |
| `Application/` | 本模块用例、应用契约、入站端口、出站端口、输入输出对象 |
| `Adapter/` | 本模块边界适配实现，包括入站适配、出站适配、转换和技术落地 |

`Src/` 一旦存在，必须至少包含一个递归含至少一个合法源码文件的源码区域（`Boot/`、`Domain/`、`Application/`、`Adapter/` 之一），或一个含至少一个合法 Import 文件的 `Import/`。空 `Src/` 或只含空区域目录是结构违规。`Src/` 直接子项除上述五个区域目录外都违规。

模块的 `<ext>` 由扩展名 census 确定，不依赖任何单一入口文件锚定：

```text
模块 <ext> = Src/ 五区域下全部"作为源码合法成形"的普通文件尾扩展名 token 去重集合（census）
census 恰一元 e   -> <ext> = e（一致性由构造成立，单文件不产生"扩展名错误"）
census 元素 ≥ 2   -> 模块扩展名冲突；<ext> 不可判定；全区域不生成结构源码文件集合与镜像期望集合
census 为空且无 Src -> <ext> N/A，合法
census 为空但 Src 存在（仅含不投票的畸形文件） -> 源码闭合错误，<ext> 不可判定
```

`<ext>` 是文件名最后一个 `.` 之后的扩展名，必须匹配：

```text
[a-z][a-z0-9_]*
```

规则：

- `<ext>` 只使用 ASCII 小写字母、数字、下划线。
- `<ext>` 必须以小写字母开头。
- 结构源码文件不使用多段扩展名。
- 同一模块的全部结构源码文件使用同一个 `<ext>`，这条由 census 定义；不一致即模块扩展名冲突。
- 非法扩展名、多段扩展名、畸形文件名的普通文件不投票进入 census，按非法源码候选独立记录源码闭合错误，不进入 census、结构源码文件集合或镜像期望集合。

普通结构源码文件名形式：

```text
<source_stem>.<ext>
```

`<source_stem>` 必须是结构路径段。`Src/Import/` 中的文件例外，其 stem 使用 Import 编码。

`Boot/`、`Import/`、`Domain/`、`Application/`、`Adapter/` 按需出现。`Boot/`、`Domain/`、`Application/`、`Adapter/` 一旦出现，必须递归包含至少一个合法源码文件。`Import/` 一旦出现，必须至少包含一个载体、命名、扩展名合法且没有 Import stem 唯一性错误的 Import 文件，并且不能包含子目录。

`Boot/`、`Domain/`、`Application/`、`Adapter/` 内部只能放结构源码文件和源码目录。源码目录名和源码文件 stem 必须符合结构路径段文法。源码目录不能为空，并且必须递归包含至少一个合法源码文件。

递归源码普通文件先按文件名形式校验，再进入源码 stem 唯一性检查。文件名必须是 `<source_stem>.<ext>`，stem 合法且扩展名等于当前模块 `<ext>`。文件名形式错误或扩展名错误的普通文件是非法源码候选，只记录源码闭合错误，不进入 stem 唯一性集合、结构源码文件集合或测试镜像期望集合。

`Boot/`、`Domain/`、`Application/`、`Adapter/` 四区与 `Import/` 的模块内依赖边界由各自专章给出，统一优先级与非具名位置判定由《依赖规则优先级》给出。

### 模块三分类与运行性蕴含

模块按"能力深度"三分，由两个布尔位驱动：是否有 Usecase（`Src/Application/Usecase/` 下递归含至少一个合法源码文件）、是否有 Adapter（`Src/Adapter/` 下递归含至少一个合法源码文件）。因 Adapter 恒蕴含 Usecase，`(Usecase, Adapter)` 的四种取值塌缩为三类（`¬Usecase ∧ Adapter` 不可能），对闭合模块互斥穷尽；违反下列位置蕴含的候选先归模块闭合错误，不进入三分类：

| 分类 | 谓词 | 形态 |
| --- | --- | --- |
| 纯数据/类型 | ¬Usecase ∧ ¬Adapter | 无 `Src/Boot`、无运行表面；可含 Domain 类型、不带 Boot 的 Application 契约类型（`Command`、`Query`、`Result`、`Dto`、`Error`、`Entry`）与非具名 Application 内部源码，不含 `Port/In`、`Port/Out`（二者经蕴含带出 Usecase/Adapter 与 `Src/Boot`） |
| 纯逻辑 | Usecase ∧ ¬Adapter | 零-Adapter 组合根：`Src/Boot` 直接装配 Usecase，把 Usecase 亮成可运行 |
| 技术 | Adapter（恒蕴含 Usecase） | `Src/Boot` 用 env 自建 Adapter、接到 Usecase，产出可运行成品 |

结构强制蕴含（机器可判定的位置规则）：

- `Usecase ⟹ Src/Boot`：有可运行能力却无组合根 = 模块闭合错误。
- `Adapter ⟹ Src/Boot`：有 Adapter 却无组合根 = 模块闭合错误。
- `Adapter ⟹ Usecase`：有 Adapter 却无 Usecase（In/Out/Mapper 调无人实现的 Port/In、实现无人消费的 Port/Out）= 模块闭合错误（悬空 Adapter）。
- `Port/In ⟹ Usecase`：暴露能力契约却无实现 = 模块闭合错误（悬空契约）。
- `Port/Out ⟹ Adapter/Out`：声明外部需求却无落地 = 模块闭合错误。
- `Import ⟹ Adapter/Out/Module`：有跨模块绑定却无消费者 = 模块闭合错误（悬空绑定）；`Src/` 仅含 `Import/` 而无任何能力区域时，按《源码结构总则》的 `Src/` 最小内容仍成立（合法 Import 文件计入），但因缺 `Adapter/Out/Module` 消费者由本蕴含归为模块闭合错误。
- `Src/Boot ⟹ Usecase`：有组合根却无可装配的 Usecase = 模块闭合错误（空转组合根）。它与 `Usecase ⟹ Src/Boot` 合成 `Src/Boot ⟺ Usecase`，故对闭合模块"有无 `Src/Boot`"与"有无 Usecase"等价，不存在 Boot-only 模块。
- 逆否：无 `Src/Boot` 的闭合模块既无 Usecase 也无 Adapter，是纯数据/类型模块；含 Usecase 或 Adapter 却缺对应 `Src/Boot` 的模块不是纯数据/类型，而是上述蕴含下的模块闭合错误候选。

上列位置蕴含是结构层（位置存在性）的"已声明 ⟹ 已实现"闭合：悬空 Adapter 由 `Adapter ⟹ Usecase` 在结构层捕获。更细的"入站适配确实指向已存在的 `Port/In`、出站适配确实实现已存在的 `Port/Out`、跨模块能力确实先经 `Port/Out` 再由 `Adapter/Out/Module` 落地"属源码依赖方向，由语言级工具补充强制（见《验证注意事项》末段），不另立结构位置蕴含；故结构扫描器不强制 `Adapter/In ⟹ Port/In` 或 `Adapter/Out ⟹ Port/Out` 这类反向位置存在性。

## Src/Boot/ 组合根

`Src/Boot/` 是 `Src/` 由内向外的最外圈组合根，吸收"组合 Usecase + Adapter、接收外部 env"的职责，是唯一既能依赖 `Application/Usecase` 又能依赖具体 Adapter 的源码区。

组合契约 `createApp(env) -> RunnableApp` 是语言级不变量（扫描器只要求 `Src/Boot/` 递归非空并校验其测试镜像；`Src/Boot/` 的模块内依赖方向属源码依赖方向，由语言级工具补充验证，见《验证注意事项》末段）：

- `env` = 配置值 + 共享基础设施句柄（如数据库连接池、时钟、ID 生成、日志 sink）+ 数据；`env` 不得是具体 Adapter，也不得是 `Port/Out` 实现集合。Boot 自己用 `env` 构造本模块的具体 Adapter、接到 Usecase 的 `Port/Out` 缝、装配 In-Adapter，产出 `RunnableApp`。这是"模块自组合、不靠外部注入具体 Adapter"的落点。
- `RunnableApp` = 由 In-Adapter（若有）+ Usecase + Out-Adapter（若有）装配出的运行成品，暴露生命周期、处理器或可调用操作；它是模块公开表面的运行 facet，由绑定 `Script/` 工作区与平台运行边界消费。

`Boot` 允许定义组合/运行期类型与装配逻辑：`Env` 类型、`RunnableApp` 类型、wiring 代码。这是 Boot 与纯绑定边界文件的根本区别——它承载真实装配，不是只做转引的纯绑定文件。但 Boot 不得定义业务、领域或 Application 契约类型（这些归 `Domain/`、`Application/`）；它只命名基础设施形态的 `env`、运行成品形态与装配。

零-Adapter Boot 合法：纯逻辑模块可只有 `Src/Boot/` + `Src/Application/Usecase/` 而无 `Src/Adapter/`。其 `createApp(env)` 直接装配 Usecase（无 Out-Adapter 因无需 Port/Out 落地、无 In-Adapter 平台翻译），`RunnableApp` 把 Usecase 暴露为可直接调用的操作（Usecase 若实现了 `Port/In` 契约则经该契约暴露，`Port/In` 缺省时由 Boot 直接暴露 Usecase），`env` 可为最小或空配置。Boot 对 Adapter 的依赖是可选的。

`Boot/` 暴露恰好一个组合入口；其内部是遵循结构路径段文法、递归非空的源码目录与文件，文件跟随模块 `<ext>`，不自定义扩展名。`createApp`/`Env`/`RunnableApp` 的具体签名与纯度由语言级工具校验。

`Boot/` 的依赖表达：

```text
Src/Boot/** -> Src/Application/**
Src/Boot/** -> Src/Adapter/**
Src/Boot/** -> Src/Boot/**
```

禁止：

```text
Src/Boot/** -X-> Src/Domain/**
Src/Boot/** -X-> Src/Import/*.<ext>
Src/Boot/** -X-> <any_other_module>/Src/**
```

Boot 是模块最外圈：Boot 依赖 Usecase 与 Adapter（构造、装配它们），任何内层都不得反向依赖 Boot；跨模块能力必须由 `Adapter/Out/Module/` 经 `Import/` 封装，故 Boot 不直碰 Import，也不直碰别的模块 `Src`，也不直碰 Domain（它组合的是拥有 Domain 的 Usecase，不绕过 Application 直碰 Domain）。向内依赖 Boot 的禁止边在《依赖规则优先级》集中给出。

## Import/ 纯绑定边界

跨模块结构依赖只通过 `Src/Import/` 中的文件表达；不存在其他位置生成结构依赖。本句是该约束的权威定义，其余章节引用此处。`Src/Import/` 的载体、命名、扩展名、编码、反解、canonical、重复检查与依赖判定规则由《Import 边界与文件编码》给出；本节只规定 Import 文件的纯绑定职责。

`Import` 文件只有纯绑定职责：

- 只绑定目标模块根（Import 编码不变，仍指目标模块根），授予目标模块的公开表面（`Application` 公开契约 ∪ 目标 `Src/Boot`，若有）。
- 只把目标模块公开表面引入当前模块的本地边界。
- 只用于生成结构依赖图边。
- 不拥有独立于目标模块导出对象的定义。

允许语义：

```text
Src/Import/<encoded_target>.<ext>
  -> <target_module>/ 公开表面（经目标模块根：Application 公开契约 ∪ 目标 Src/Boot）
```

禁止语义：

- 不定义新的类型、接口、类、函数、常量、枚举、错误、配置、默认值或业务对象。
- 不实现适配逻辑。
- 不实现数据转换。
- 不实现业务逻辑。
- 不读取环境变量、文件、网络、进程参数或运行时状态。
- 不依赖当前模块 `Domain/`、`Application/`、`Adapter/` 或 `Boot/`。
- 不依赖目标模块公开表面之外的任何文件。
- 不把目标模块内部路径暴露给当前模块其他区域。

允许被依赖：

```text
Src/Adapter/Out/Module/**
```

禁止被依赖：

```text
Src/Domain/**      -X-> Src/Import/*.<ext>
Src/Application/** -X-> Src/Import/*.<ext>
Src/Boot/**        -X-> Src/Import/*.<ext>
```

推荐跨模块调用链：

```text
Src/Application/Usecase/**
  -> Src/Application/Port/Out/**
  <- Src/Adapter/Out/Module/**
       -> Src/Import/<encoded_target>.<ext>
          -> <target_module>/ 公开表面
```

Application 与 Boot 都不直接依赖 Import。跨模块能力必须先被当前模块表达为 `Application/Port/Out`，再由 `Adapter/Out/Module` 通过 `Import/` 落地；Boot 经本模块 `Adapter/Out/Module` 间接取用跨模块能力。

## Domain/ 区域

`Src/Domain/` 是模块最内层。它承载本模块业务事实、业务规则、领域对象和纯业务关系。它不知道 Application、Adapter、Import、Boot、数据库、HTTP、消息队列、文件系统、第三方 SDK、进程、环境变量或其他模块。

推荐结构：

```text
Src/Domain/
  Value/
  Model/
  Event/
  Policy/
  Service/
  Error/
```

### Domain/Value/

值对象。用于表达业务值、格式、范围、相等性和局部不变量。

示例：

```text
Src/Domain/Value/Money.<ext>
Src/Domain/Value/Email.<ext>
Src/Domain/Value/OrderId.<ext>
```

依赖：

```text
Src/Domain/Value/** -> Src/Domain/Value/**
Src/Domain/Value/** -> Src/Domain/Error/**
```

### Domain/Model/

实体、聚合、核心业务对象。用于表达生命周期、状态转移和聚合内不变量。

示例：

```text
Src/Domain/Model/Order.<ext>
Src/Domain/Model/OrderItem.<ext>
Src/Domain/Model/Invoice.<ext>
```

依赖：

```text
Src/Domain/Model/** -> Src/Domain/Value/**
Src/Domain/Model/** -> Src/Domain/Event/**
Src/Domain/Model/** -> Src/Domain/Error/**
Src/Domain/Model/** -> Src/Domain/Model/**
```

### Domain/Event/

领域事件。表达领域内已经发生的事实，不表达消息系统、topic、broker、队列、序列化格式或发布机制。

示例：

```text
Src/Domain/Event/OrderCreated.<ext>
Src/Domain/Event/PaymentConfirmed.<ext>
```

依赖：

```text
Src/Domain/Event/** -> Src/Domain/Value/**
Src/Domain/Event/** -> Src/Domain/Error/**
```

### Domain/Policy/

业务策略、规则、规格、判定口径。

示例：

```text
Src/Domain/Policy/DiscountPolicy.<ext>
Src/Domain/Policy/CreditLimitPolicy.<ext>
```

依赖：

```text
Src/Domain/Policy/** -> Src/Domain/Value/**
Src/Domain/Policy/** -> Src/Domain/Model/**
Src/Domain/Policy/** -> Src/Domain/Error/**
```

### Domain/Service/

领域服务。只放无法自然归属到某个实体、聚合或值对象上的纯业务规则。

示例：

```text
Src/Domain/Service/PricingService.<ext>
Src/Domain/Service/OrderEligibilityService.<ext>
```

依赖：

```text
Src/Domain/Service/** -> Src/Domain/Value/**
Src/Domain/Service/** -> Src/Domain/Model/**
Src/Domain/Service/** -> Src/Domain/Policy/**
Src/Domain/Service/** -> Src/Domain/Error/**
```

### Domain/Error/

领域错误。表达违反业务不变量、非法状态、非法值和领域规则拒绝。

示例：

```text
Src/Domain/Error/InvalidOrderState.<ext>
Src/Domain/Error/InsufficientCredit.<ext>
```

依赖：

```text
Src/Domain/Error/** -> Src/Domain/Error/**
```

若 Domain 需要时间、随机数、外部标识分配、存储、网络、当前用户、配置或其他模块数据，必须把这些需求上提为 `Application/Port/Out`，由 Application 编排，由 Adapter 实现，由 Boot 装配。

## Application/ 区域

`Src/Application/` 表达模块能做什么、需要什么外部能力、输入输出是什么、用例如何编排领域规则。Application 内部依赖中，具名子节位置按本节各小节的允许清单和禁止清单封闭判定，非具名位置按《依赖规则优先级》区域级基线判定；只有 `Application/Usecase/**` 可以直接依赖 Domain。Application 不能依赖 Adapter、Import 或 Boot。

推荐结构：

```text
Src/Application/
  Port/
    In/
    Out/
  Entry/
  Command/
  Query/
  Result/
  Dto/
  Usecase/
  Error/
```

### Application/Port/In/

入站端口。定义外部可调用的模块能力契约。

示例：

```text
Src/Application/Port/In/CreateOrderUseCase.<ext>
Src/Application/Port/In/CancelOrderUseCase.<ext>
Src/Application/Port/In/GetOrderQuery.<ext>
```

依赖：

```text
Src/Application/Port/In/** -> Src/Application/Command/**
Src/Application/Port/In/** -> Src/Application/Query/**
Src/Application/Port/In/** -> Src/Application/Result/**
Src/Application/Port/In/** -> Src/Application/Dto/**
Src/Application/Port/In/** -> Src/Application/Error/**
```

### Application/Port/Out/

出站端口，是模块内自接缝（self-seam），不是公开契约。`Port/Out` 由 Usecase 声明所需外部能力，由本模块 `Adapter/Out` 实现、由本模块 `Src/Boot` 装配绑定；它不表达技术来源，不属于公开表面，不被 Import 授予，不被消费方引用。接缝在模块内闭合：`Usecase -> Port/Out <- Adapter/Out`，由 `Src/Boot` 连接。

示例：

```text
Src/Application/Port/Out/OrderStore.<ext>
Src/Application/Port/Out/PaymentGateway.<ext>
Src/Application/Port/Out/UserProfileLookup.<ext>
Src/Application/Port/Out/DomainEventSink.<ext>
```

依赖：

```text
Src/Application/Port/Out/** -> Src/Application/Dto/**
Src/Application/Port/Out/** -> Src/Application/Result/**
Src/Application/Port/Out/** -> Src/Application/Error/**
```

原则上 `Port/Out` 不直接暴露 Domain 类型。若必须传递领域状态，优先在 Application 层定义快照、命令、结果或 DTO，让 Adapter 只理解 Application contract。

### Application/Entry/

应用入口，是可选的公开契约门面。Entry 声明本模块可被直接编程调用的应用级 API 契约（可调用操作的类型/接口聚合），零装配、纯类型/契约。Entry 不是平台启动器，不是组合根，不读取环境变量、文件、网络、进程参数或运行时状态。模块的可运行成品类型 `RunnableApp` 由 `Src/Boot` 承载，不在 Entry；Entry 仅在模块希望对外提供一组细粒度可编程契约时出现，否则可缺席。

示例：

```text
Src/Application/Entry/OrderApplication.<ext>
Src/Application/Entry/OrderCommandApi.<ext>
Src/Application/Entry/OrderQueryApi.<ext>
```

依赖：

```text
Src/Application/Entry/** -> Src/Application/Port/In/**
Src/Application/Entry/** -> Src/Application/Command/**
Src/Application/Entry/** -> Src/Application/Query/**
Src/Application/Entry/** -> Src/Application/Result/**
Src/Application/Entry/** -> Src/Application/Dto/**
Src/Application/Entry/** -> Src/Application/Error/**
```

禁止：

```text
Src/Application/Entry/** -X-> Src/Domain/**
Src/Application/Entry/** -X-> Src/Application/Usecase/**
Src/Application/Entry/** -X-> Src/Adapter/**
Src/Application/Entry/** -X-> Src/Import/*.<ext>
Src/Application/Entry/** -X-> Src/Boot/**
Src/Application/Entry/** -X-> <any_other_module>/Src/**
```

### Application/Command/

写操作输入对象。表达改变状态的用例输入。

示例：

```text
Src/Application/Command/CreateOrderCommand.<ext>
Src/Application/Command/CancelOrderCommand.<ext>
```

依赖：

```text
Src/Application/Command/** -> Src/Application/Dto/**
Src/Application/Command/** -> Src/Application/Error/**
```

### Application/Query/

读操作输入对象。表达查询用例输入。

示例：

```text
Src/Application/Query/GetOrderByIdQuery.<ext>
Src/Application/Query/ListOrdersQuery.<ext>
```

依赖：

```text
Src/Application/Query/** -> Src/Application/Dto/**
Src/Application/Query/** -> Src/Application/Error/**
```

### Application/Result/

用例返回结果。表达 Application contract 的输出，不暴露 Adapter 技术对象。

示例：

```text
Src/Application/Result/CreateOrderResult.<ext>
Src/Application/Result/OrderDetailResult.<ext>
```

依赖：

```text
Src/Application/Result/** -> Src/Application/Dto/**
Src/Application/Result/** -> Src/Application/Error/**
```

### Application/Dto/

应用层数据传输结构。用于隔离 Domain Model、外部协议对象和持久化记录。

示例：

```text
Src/Application/Dto/OrderLineData.<ext>
Src/Application/Dto/MoneyData.<ext>
```

依赖：

```text
Src/Application/Dto/** -> Src/Application/Dto/**
```

### Application/Usecase/

用例实现。编排 Domain，调用 `Port/Out`，实现 `Port/In` 契约。

示例：

```text
Src/Application/Usecase/CreateOrderService.<ext>
Src/Application/Usecase/CancelOrderService.<ext>
Src/Application/Usecase/GetOrderService.<ext>
```

依赖：

```text
Src/Application/Usecase/** -> Src/Domain/**
Src/Application/Usecase/** -> Src/Application/Port/In/**
Src/Application/Usecase/** -> Src/Application/Port/Out/**
Src/Application/Usecase/** -> Src/Application/Command/**
Src/Application/Usecase/** -> Src/Application/Query/**
Src/Application/Usecase/** -> Src/Application/Result/**
Src/Application/Usecase/** -> Src/Application/Dto/**
Src/Application/Usecase/** -> Src/Application/Error/**
```

禁止：

```text
Src/Application/Usecase/** -X-> Src/Adapter/**
Src/Application/Usecase/** -X-> Src/Import/*.<ext>
Src/Application/Usecase/** -X-> Src/Boot/**
Src/Application/Usecase/** -X-> <any_other_module>/Src/**
```

Usecase 是内部位置（非公开表面），但它的存在是模块可运行性的充要驱动：`Usecase ⟹ Src/Boot`（见《源码结构总则·模块三分类与运行性蕴含》）。

### Application/Error/

应用层错误。表达用例拒绝、资源不可用、输入不满足用例条件、外部能力失败的 Application 语义。

示例：

```text
Src/Application/Error/UseCaseRejected.<ext>
Src/Application/Error/ResourceNotFound.<ext>
```

依赖：

```text
Src/Application/Error/** -> Src/Application/Error/**
```

如需保留领域错误原因，只能通过 Application 错误进行归一化表达，不能把 Domain 错误作为跨模块公共事实泄漏。

## Adapter/ 区域

`Src/Adapter/` 是当前模块的边界适配实现。它负责把外部输入变成 Application 调用，把 Application 需要的外部能力落地，并完成对象转换。Adapter 内部依赖中，具名子节位置按本节各小节的允许清单和禁止清单封闭判定，非具名位置按《依赖规则优先级》区域级基线判定；只有 `Adapter/Out/Module/` 可以依赖 `Src/Import/*.<ext>`；Adapter 内其他区域不得依赖 Import。Adapter 不直接依赖 Domain；Domain 只被 Application 使用。Adapter 不依赖 `Application/Usecase/**`，也不依赖 `Src/Boot/**`——组合 Usecase 的唯一区是 `Src/Boot`，装配责任不回流 Adapter。

推荐结构：

```text
Src/Adapter/
  In/
    Web/
    Cli/
    Message/
    Schedule/
  Out/
    Persistence/
    Messaging/
    External/
    Module/
  Mapper/
```

### Adapter/In/

入站适配器。把平台、协议或外部输入转换为 Application Port In 调用。

示例：

```text
Src/Adapter/In/Web/OrderController.<ext>
Src/Adapter/In/Cli/CreateOrderCommandHandler.<ext>
Src/Adapter/In/Message/OrderMessageConsumer.<ext>
Src/Adapter/In/Schedule/OrderCleanupJob.<ext>
```

依赖：

```text
Src/Adapter/In/** -> Src/Application/Port/In/**
Src/Adapter/In/** -> Src/Application/Command/**
Src/Adapter/In/** -> Src/Application/Query/**
Src/Adapter/In/** -> Src/Application/Result/**
Src/Adapter/In/** -> Src/Application/Dto/**
Src/Adapter/In/** -> Src/Application/Error/**
Src/Adapter/In/** -> Src/Adapter/Mapper/**
```

禁止：

```text
Src/Adapter/In/** -X-> Src/Domain/**
Src/Adapter/In/** -X-> Src/Import/*.<ext>
Src/Adapter/In/** -X-> Src/Boot/**
Src/Adapter/In/** -X-> <any_other_module>/Src/**
```

本节清单约束 `Adapter/In/` 下的具名子节（`Web/`、`Cli/`、`Message/`、`Schedule/` 等叶子）；直接位于 `Src/Adapter/In/` 或其下非具名自定义子目录（如 `Src/Adapter/In/<other_segment>/`）的源码文件属于 `Adapter/` 的非具名位置，按《依赖规则优先级》区域级基线治理，不套用本节具名子节清单（口径与《Adapter/ 区域》末尾对 `Src/Adapter/Out/` 的处理一致）。

### Adapter/Out/

出站适配器。实现 Application Port Out。它把 Application 需要的外部能力落地到存储、消息、第三方服务、文件、系统 API 或其他模块。

推荐子目录：

| 目录 | 语义 |
| --- | --- |
| `Adapter/Out/Persistence/` | 数据库存储、文件存储、对象存储、索引存储等持久化落地 |
| `Adapter/Out/Messaging/` | 消息发布、事件投递、队列写入、通知发送 |
| `Adapter/Out/External/` | 第三方 API、远程服务、SDK、平台服务 |
| `Adapter/Out/Module/` | 通过 `Src/Import/` 调用其他模块的出站适配器 |

示例：

```text
Src/Adapter/Out/Persistence/SqlOrderStore.<ext>
Src/Adapter/Out/Messaging/KafkaDomainEventSink.<ext>
Src/Adapter/Out/External/StripePaymentGateway.<ext>
Src/Adapter/Out/Module/UserProfileLookupFromUserModule.<ext>
```

依赖：

```text
Src/Adapter/Out/** -> Src/Application/Port/Out/**
Src/Adapter/Out/** -> Src/Application/Dto/**
Src/Adapter/Out/** -> Src/Application/Result/**
Src/Adapter/Out/** -> Src/Application/Error/**
Src/Adapter/Out/** -> Src/Adapter/Mapper/**
Src/Adapter/Out/Persistence/** -> Src/Adapter/Out/Persistence/**
Src/Adapter/Out/Messaging/** -> Src/Adapter/Out/Messaging/**
Src/Adapter/Out/External/** -> Src/Adapter/Out/External/**
Src/Adapter/Out/Module/** -> Src/Adapter/Out/Module/**
```

`Adapter/Out/Module/` 额外允许：

```text
Src/Adapter/Out/Module/** -> Src/Import/*.<ext>
```

禁止：

```text
Src/Adapter/Out/** -X-> Src/Domain/**
Src/Adapter/Out/** -X-> Src/Boot/**
Src/Adapter/Out/** -X-> <any_other_module>/Src/**
Src/Adapter/Out/Persistence/** -X-> Src/Import/*.<ext>
Src/Adapter/Out/Messaging/**   -X-> Src/Import/*.<ext>
Src/Adapter/Out/External/**    -X-> Src/Import/*.<ext>
```

只有 `Adapter/Out/Module/` 可以依赖 `Src/Import/*.<ext>`。直接位于 `Src/Adapter/Out/` 或位于 `Src/Adapter/Out/` 下非具名自定义子目录（如 `Src/Adapter/Out/<other_segment>/`）的源码文件，属于 `Adapter/` 的非具名位置，按《依赖规则优先级》区域级基线治理，不享有 `Adapter/Out/Module/` 对 `Src/Import/*.<ext>` 的额外许可，也不享有 `Persistence/`、`Messaging/`、`External/`、`Module/` 四个具名子节内部各自的自指边许可。

### Adapter/Mapper/

边界转换器。负责协议对象、持久化记录、外部 DTO、Application DTO、Result、Command、Query 之间的转换。

示例：

```text
Src/Adapter/Mapper/OrderRecordMapper.<ext>
Src/Adapter/Mapper/OrderResponseMapper.<ext>
Src/Adapter/Mapper/UserProfileMapper.<ext>
```

依赖：

```text
Src/Adapter/Mapper/** -> Src/Application/Command/**
Src/Adapter/Mapper/** -> Src/Application/Query/**
Src/Adapter/Mapper/** -> Src/Application/Result/**
Src/Adapter/Mapper/** -> Src/Application/Dto/**
Src/Adapter/Mapper/** -> Src/Application/Error/**
Src/Adapter/Mapper/** -> Src/Adapter/Mapper/**
```

禁止：

```text
Src/Adapter/Mapper/** -X-> Src/Domain/**
Src/Adapter/Mapper/** -X-> Src/Import/*.<ext>
Src/Adapter/Mapper/** -X-> Src/Boot/**
Src/Adapter/Mapper/** -X-> <any_other_module>/Src/**
```

## 依赖规则优先级

模块内依赖以前文各区域小节的允许清单和禁止清单，叠加本节给出的区域级基线为准；区域级基线与各小节清单并列权威，专门授予非具名位置的正向区域内边。具名推荐子目录（如 `Domain/Value/`、`Application/Command/`、`Adapter/Out/Module/`）下的源码文件按其所在子节的允许清单封闭判定：清单内的模块内边允许，清单外的模块内边违规。各区域专章依赖清单里作为分组前缀出现的 glob（如 `Src/Adapter/In/**`、`Src/Adapter/Out/**`，以及各专章引言泛指整区的 `Src/<region>/**`）只约束落入其下具名子节（叶子级子目录）的源码文件；不落入任何具名子节的非具名位置不受这些专章清单约束，仅由本节区域级基线与下文跨区域禁止方向治理（《Adapter/ 区域》末尾已就 `Src/Adapter/Out/` 点明此口径，其余分组前缀同理）。

`Domain/`、`Application/`、`Adapter/`、`Boot/` 内部还可出现合法但非具名位置的源码文件，例如直接位于 `Src/Domain/` 的源码文件，或直接位于 `Src/Domain/` 之下、名称合法却不在推荐清单内的自定义目录（如 `Src/Domain/<other_segment>/`）。具名子节是各区域专章推荐清单给出的叶子级子目录，其 glob 形如 `Src/<region>/<named_subsection_path>/**`，`<named_subsection_path>` 是从顶层区域根到该具名子节叶子的完整路径段，可以是一段（如 `Value`、`Command`），也可以是多段（如 `In/Web`、`Out/Module`）。`Adapter/In/`、`Adapter/Out/` 这类只承担分组的中间前缀本身不是具名子节；`Adapter/Out/` 下的具名子节是 `Persistence/`、`Messaging/`、`External/`、`Module/` 四个叶子。是否落入具名子节只按具名子节的 `Src/<region>/<named_subsection_path>/**` glob 子树归属判定，不按目录名是否在推荐清单内判定；源码文件由包含它的、glob 最深的那个具名子节封闭治理，嵌套在某个具名子节子树内部的自定义名目录（如 `Src/Adapter/Out/Module/<other_segment>/`、`Src/Application/Usecase/<other_segment>/`）继承该具名子节的封闭允许清单，不享区域级基线。一个源码文件属于非具名位置当且仅当它不落入其所在顶层区域内任何具名子节的 `Src/<region>/<named_subsection_path>/**` 子树；这类文件无论直接位于顶层区域根 `Src/<region>/`，还是位于区域内某分组前缀下、不落入任何具名子节子树的非具名自定义目录中（如 `Src/Adapter/Out/<other_segment>/`，它是 `Persistence/`、`Messaging/`、`External/`、`Module/` 四个具名子节的兄弟），只要不被任何具名子节子树包含，就一律按其所在顶层区域的区域级基线判定模块内正向边：

- `Src/Domain/**` 内非具名位置源码可依赖本模块 `Src/Domain/**`。
- `Src/Application/**` 内非具名位置源码可依赖本模块 `Src/Application/**`。
- `Src/Adapter/**` 内非具名位置源码可依赖本模块 `Src/Adapter/**` 与 `Src/Application/**`（其中 `Application/Usecase/**` 由下文 Adapter 跨区域禁止方向扣除：Adapter 任何位置都不依赖 Usecase）。
- `Src/Boot/**` 内非具名位置源码可依赖本模块 `Src/Boot/**`、`Src/Application/**` 与 `Src/Adapter/**`。

区域级基线补全非具名位置的区域内正向边，以及各区域引言允许的跨区域正向边（Adapter 非具名位置对 `Src/Application/**` 的依赖；Boot 非具名位置对 `Src/Application/**` 与 `Src/Adapter/**` 的依赖）；其余仍受各区域引言给出的跨区域禁止方向约束：Domain 不依赖 Application、Adapter、Import、Boot 或其他模块；Application 不依赖 Adapter、Import、Boot 或其他模块；Adapter 不依赖 Domain、Usecase、Boot 或其他模块；Boot 不依赖 Domain、Import 或其他模块。`Src/Boot/` 是唯一既可依赖 `Application/Usecase/**` 又可依赖具体 Adapter 的区（组合根）；`Application/Usecase/**` 与 `Adapter/Out/Module/**` 两个具名子目录分别保有对 `Domain/` 与 `Src/Import/*.<ext>` 的额外许可，非具名位置不享有该许可。本文件不设置放宽这些边界的全局汇总矩阵；任何摘要性说明都不能放宽 `Domain/`、`Application/`、`Adapter/`、`Boot/`、`Import/` 或 `Script/` 小节已经给出的白名单边界。

向内依赖 Boot 一律禁止（Boot 是最外圈，任何向内依赖 Boot 都会成环或把装配逻辑泄漏进行为层）：

```text
Src/Domain/**      -X-> Src/Boot/**
Src/Application/** -X-> Src/Boot/**
Src/Adapter/**     -X-> Src/Boot/**
Src/Import/*.<ext> -X-> Src/Boot/**

Src/Boot/** -X-> Src/Domain/**
Src/Boot/** -X-> Src/Import/*.<ext>
Src/Boot/** -X-> <any_other_module>/Src/**
```

若两个规则看似冲突，按更具体的位置规则执行。例如 `Application/Usecase/` 的规则优先于 `Application/` 区域说明，`Adapter/Out/Module/` 的规则优先于 `Adapter/Out/` 区域说明，`Src/Import/*.<ext>` 的纯绑定规则优先于任何跨模块依赖说明。

`Import` 是边界文件，不是业务层，只做纯绑定、自身不定义任何内容；若它需要定义内容，说明内容应该进入 `Adapter/` 或目标模块自身。`Boot` 不是纯绑定边界文件，而是承载真实装配的组合根；若 Boot 需要定义业务或契约类型，说明这些内容应该进入 `Application/` 或 `Domain/`。

## 脚本调用边界

模块的 `Script/` 和模块的 `Src/` 是两个东西。

```text
<module>/Src/     = 模块能力定义与实现
<module>/Script/  = 绑定当前模块的平台特化调用入口集合
```

脚本项目的职责：

- 读取平台输入，例如命令行参数、环境变量、运行目录、CI 参数、部署平台参数。
- 调用目标模块 `Src/Boot` 的 `createApp` 取得并运行 `RunnableApp`，或引用目标模块 `Application` 公开契约构造输入。
- 把调用结果交还给平台，例如退出码、标准输出、HTTP 响应、任务状态。
- 表达平台特化运行方式，例如 CLI、worker、cron、server、migration runner。

脚本项目的禁止职责：

- 不成为目标模块 `Src` 的组成部分。
- 不定义可被目标模块依赖的业务能力。
- 不让目标模块 `Src` 反向依赖脚本。
- 不直接调用目标模块 `Src/Domain/**`。
- 不直接调用目标模块 `Src/Application/Usecase/**` 或 `Src/Application/Port/Out/**`（内部位置）。
- 不直接调用目标模块 `Src/Adapter/**`。
- 不直接调用目标模块 `Src/Import/*.<ext>`。
- 不穿透调用其他模块内部文件。

脚本对目标模块的调用边界：

```text
<module>/Script/<script_project>/** -> <module>/Src/Boot/**            （createApp/RunnableApp 运行入口）
<module>/Script/<script_project>/** -> <module>/Src/Application/<public_contract_section>/**   （构造输入用）
```

禁止：

```text
<module>/Script/<script_project>/** -X-> <module>/Src/Domain/**
<module>/Script/<script_project>/** -X-> <module>/Src/Application/Usecase/**
<module>/Script/<script_project>/** -X-> <module>/Src/Application/Port/Out/**
<module>/Script/<script_project>/** -X-> <module>/Src/Adapter/**
<module>/Script/<script_project>/** -X-> <module>/Src/Import/*.<ext>
```

项目级 `Script/` 工作区可以调用其所在项目内的 Main 模块表面；模块级 `Script/` 工作区只调用它绑定的直接父模块表面。若脚本需要组合多个模块，应优先调用所在项目的 Main 模块表面，而不是直接拼接多个 Package 模块内部对象。

本节是脚本调用边界的权威定义，其余章节引用此处。脚本对目标模块公开表面（`Src/Boot` 运行表面与 Application 公开契约）的调用是非构成性边界，与跨模块构成性依赖图相互独立：它经语言级直接调用目标模块公开表面，不经 `Src/Import/`，不生成结构依赖图边，不进入 Main/Package 依赖规则，也不进入 Package 环检测。脚本调用目标模块公开表面，是模块公开表面面向外部调用方（脚本、平台、运行边界）的指定用法；结构扫描器不为脚本调用生成依赖边，该调用边界由语言级工具补充强制。该非构成性平台级调用也是《环境与依赖解析边界·强制归口》中"跨模块语言级引用必须经 `Src/Import/` 绑定"的唯一例外。

脚本项目本身仍是项目，其内部 Main/Package 模块按通用模块规则组织 `Src/`。脚本项目内部模块之间的构成性跨模块依赖仍只经各自 `Src/Import/` 与 Main/Package 依赖规则表达，并照常进入依赖图与 Package 环检测；只有"脚本项目调用其绑定模块或所在项目 Main 模块的公开表面"这一条平台级调用属于本节的非构成性边界。脚本逻辑落在脚本项目模块的 `Src/Adapter/In/**`（如 `Adapter/In/Cli/**`）等入站位置，由这些入站位置对目标模块公开表面发起平台级调用。该平台级调用是非构成性的（不经 `Src/Import/`、不生成依赖边），不属于《Adapter/ 区域》对 `Adapter/In/**` 所禁止的跨模块构成性依赖边——后者只禁止经结构依赖图的构成性跨模块边，本节确立的非构成性平台级调用是其唯一例外。

## Import 边界与文件编码

跨模块结构依赖只经 `Src/Import/` 表达（权威定义见《Import/ 纯绑定边界》）。只有模块需要表达跨模块结构依赖时才需要 `Src/Import/`；没有 Import 文件时，`Src/Import/` 不能存在。跨模块依赖必须先进入 `Src/Import/`，再由 `Adapter/Out/Module/` 读取这些本地 Import 绑定。

`Src/Import/` 只放 Import 文件，不放子目录。Import 文件 stem 必须是合法 Import 编码，扩展名必须等于当前模块 `<ext>`。普通 Import 文件的文件名文法错误和扩展名错误记为第一阶段 `Src` 闭合错误（findingKind 为结构闭合错误），并在第二阶段同样作为该 Import 文件的累计错误，阻断其反解、canonical、重复、依赖检查与合法依赖边生成；它们不另立独立 Import 诊断 findingKind 类别（第一步检查中唯一独立成 Import findingKind 的是 Import stem 唯一性错误）。`Src/Import/` 中的子目录、符号链接、特殊文件或其他非普通文件，只记录第一阶段闭合错误，不形成第二阶段 Import 诊断项。

Import 文件名由当前模块根目录到目标模块根目录的相对路径编码生成。编码基准是当前模块根目录，不是当前源码文件所在目录。文件对应目标模块根目录，授予目标模块公开表面（`Application` 公开契约 ∪ 目标 `Src/Boot`），不指向任何单一入口文件，绝不对应目标模块内部任意文件。

编码形式：

```text
<up_count>(-<down_segment>)+
```

规则：

- `<up_count>` 是十进制非负整数。
- `0` 表示不上溯。
- 非零数值不允许前导零。
- canonical `<up_count>` 表示从当前模块根目录上溯到当前模块根目录与目标模块根目录的最近共同祖先需要跨过的路径段数量。
- 最近共同祖先必须位于同一个产品工作区内，不能越过扫描输入根。
- 下行路径段按真实目录名依次写入，并用 `-` 连接。
- 不使用 `..` 表示上级目录。
- Import 编码 stem 文法是 `^(0|[1-9][0-9]*)(-[A-Za-z][A-Za-z0-9_]*)+$`。
- 下行路径片段可以包含合法位置上的结构目录名，例如 `Vendor`、`Main`、`Package`；这些片段按路径位置解释，不按项目名或模块名解释。
- 因为结构路径段不使用 `-`，Import 编码可从左到右反解；不存在对包含 `-` 的真实路径名的转义。

路径反解使用文件系统原始名称做精确大小写匹配，不使用 `realpath`，不跟随符号链接。反解在第一阶段结构候选图内进行。声明的 `<up_count>` 按文件名字面执行；是否为最近共同祖先形式由后续 canonical 检查判定。

合法上溯终点只能是产品工作区根、项目目录候选、模块角色空间候选、模块目录候选或内嵌工作区候选。上溯终点不能是自由余项、`Config/`、`Data/`、`Src/`、`Test/` 或 `Bin/` 内部路径。

Import 诊断结果：

- 上溯到产品工作区输入根之上：Import 越界。
- 路径不存在：Import 目标缺失。
- 路径存在但中途遇到普通文件、自由余项、`Config/`、`Data/`、`Src/`、`Test/`、`Bin/`、非法项目候选、非法模块角色空间候选、非法内嵌工作区候选、唯一性冲突候选或其他非合法定位的中间结构候选：Import 路径非法；不能穿透该项继续反解。
- 最终位置不是模块候选：Import 目标非模块。
- 最终模块候选不能成为合法模块：Import 目标模块结构非法。
- 目标是当前模块：Import 自依赖。
- 目标是从产品工作区根到当前模块根的结构路径上的祖先模块，且不是当前模块自身：Import 祖先依赖。
- 目标合法但不可依赖：Import 目标不可依赖。
- 目标可依赖但 Main/Package 依赖规则拒绝：Import 依赖违规。

以上是路径反解阶段的 Import 诊断；另有三类 Import 诊断由下文 Import 校验顺序给出：Import stem 唯一性错误（第 1 步）、非 canonical Import（第 4 步）、重复 Import（第 5 步）。此九项反解诊断与该三项合为 `findingKind` 的十二类 Import 诊断全集（与《验证注意事项》`findingKind` 行一致）。

自依赖和祖先依赖 Import 不参与 canonical 检查、重复 Import 检查、目标可依赖性检查或 Main/Package 依赖口径检查。

canonical Import stem 是最短合法编码。根据从扫描输入根到各模块根目录的真实结构路径段数组计算。

外层工作区 profile 的数组包含产品项目名、模块角色空间名、模块名、内嵌工作区名、内嵌项目名，以及路径中后续模块角色空间名和模块名。产品项目根 profile 的数组不包含输入根 basename，不包含虚拟项目名，从根项目直接结构子项开始，例如：

```text
Main/GameClientWeb
Package/BaselineSupply
Tool/Structure/Main/StructureCli
```

两种 profile 的数组都不包含 `Src`、`Test`、`Config`、`Data`、`Import`、源码目录名、测试目录名或文件名。

当前模块根数组记为 `A`，目标模块根数组记为 `B`，最长公共前缀记为 `P`，则：

```text
up_count = len(A) - len(P)
down_segments = B without P
```

canonical stem 由 `up_count` 和 `down_segments` 用 `-` 连接得到。下行路径片段不能为空；若 `B` 去掉 `P` 后为空，则目标不是可编码的合法 Import 目标。

Import 校验按固定顺序累计错误：

1. 检查 Import 文件名文法、扩展名和 Import 编码 stem 唯一性。
2. 第 1 步通过后，按声明路径反解。
3. 路径落到模块候选后，检查自依赖和祖先依赖。
4. 非自依赖且非祖先依赖时，计算并检查 canonical stem。
5. 对同一源模块内所有能反解到同一目标模块候选且不是自依赖或祖先依赖的文件，执行重复 Import 检查；不要求这些文件已经通过 canonical 或目标合法性检查。该检查同时强制"同一模块对同一目标模块最多一个 Import 文件"。
6. 随后检查目标模块合法性、目标可依赖性和 Main/Package 依赖规则。

文件名文法、扩展名或 Import stem 唯一性错误会阻止路径反解、canonical 检查、重复检查和依赖检查。未落到模块候选的 Import 不参与 canonical、重复或依赖检查。重复 Import 等价类中的全部成员都累计重复错误；不保留任何一个作为有效代表。任何累计至少一个 Import 错误的文件都不生成合法依赖边。

示例：

```text
<project_alpha>/Main/<module_alpha>/
<project_alpha>/Package/<module_beta>/
Src/Import/2-Package-<module_beta>.<ext>
```

```text
<project_alpha>/Package/<module_alpha>/
<project_alpha>/Package/<module_alpha>/Vendor/<project_beta>/Main/<module_beta>/
Src/Import/0-Vendor-<project_beta>-Main-<module_beta>.<ext>
```

## 测试结构

`Test/` 是 `Src/` 的严格镜像。`Src/` 中每个结构源码文件都必须有镜像测试。模块没有 `Src/` 时不能出现 `Test/`；模块存在 `Src/`（含至少一个合法源码或 Import 文件）时必须出现 `Test/`。

```text
Test/
  Import/
    <encoded_relative_module_path>.Test.<ext>
  Boot/
  Domain/
  Application/
  Adapter/
```

测试文件名形式：

```text
<mirrored_source_stem>.Test.<ext>
```

规则：

- 测试文件名不是单一结构路径段。
- `<mirrored_source_stem>` 必须对应源码文件 stem。
- 普通源码文件镜像普通源码 stem。
- `Src/Import/` 文件镜像 Import 编码 stem。
- `.Test` 是固定测试后缀。
- 测试 `<ext>` 必须等于当前模块源码扩展名。
- 需要镜像的结构源码文件包括合法 `Src/Import/` 文件，以及 `Boot/`、`Domain/`、`Application/`、`Adapter/` 下的全部源码文件。
- 只有载体、命名、扩展名合法且没有 Import stem 唯一性错误的 `Src/Import/` 普通文件进入镜像期望集合。
- 文件名错误、扩展名错误、唯一性错误、子目录、符号链接、特殊文件或其他非 Import 文件不进入镜像期望集合。
- `Test/Import/` 只镜像 `Src/Import/` 文件名，不表达依赖，也不生成依赖图边。
- `Test/` 直接子项 `Boot/`、`Import/`、`Domain/`、`Application/`、`Adapter/` 皆目录，`Test/` 直接子项不允许任何普通文件。

镜像文件位于相同相对路径下，并在源码 stem 后增加 `.Test`。镜像 stem 和目录段必须与源码 stem 和目录段完全一致；只按 ASCII 折叠相等但原始名称不同时，期望的精确同名镜像按测试镜像缺失记录、该折叠重名文件或目录按测试镜像多余记录，不另立独立 findingKind 类别。

只有对应 `Src/Boot/` 存在至少一个源码文件时，才允许出现 `Test/Boot/`。`Domain/`、`Application/`、`Adapter/`、`Import/` 同理。中间镜像目录只要通向期望测试文件即可，不要求自身直接包含文件。`Src/` 中没有源码文件后代的目录不要求在 `Test/` 中出现。

`Test/` 只能包含实际源码文件路径需要的镜像目录和镜像测试文件；不能包含自由余项、非测试文件、没有对应源码文件的测试文件或没有对应源码路径的目录。

可复用测试过程必须属于某个结构源码文件的镜像测试，或者成为本模块 `Src/` 中可被测试的过程文件并获得自己的镜像测试。测试数据不进入 `Test/`，进入 `Data/Test/`。测试代码验证本模块 `Src`；需要读取外部模块时，仍通过本模块 `Src/Import/` 边界。

如果 `Src/` 存在但模块扩展名不可判定（census 冲突，或 census 为空而 Src 非空），缺失的 `Test/` 仍记录为测试保留项缺失错误。若此时 `Test/` 已存在，它不能成为合法测试镜像；只对其做载体验证，记录测试镜像不可判定，不推断 `<ext>`，也不生成镜像期望集合。

## Config、Data 与 Bin

`Config/` 表达过程不变量，不承载测试数据，也不承载过程产物。它没有固定保留子项；内部内容按数据载体处理，不递归识别工作区、项目、模块或源码结构。`Config/` 一旦出现，必须递归包含至少一个普通文件。

`Data/` 表达模块数据。其唯一直接保留子项是 `Test/`；其他内部内容按数据载体处理，不递归识别结构。模块可以在没有 `Src/` 和 `Test/` 的情况下拥有 `Data/Test/`，因为测试数据是数据载体，不是测试过程。`Data/` 一旦出现，必须递归包含至少一个普通文件；`Data/Test/` 内的普通文件计入。

`Data/` 直接子项名称按 ASCII 折叠后等于 `Test` 时，必须使用规范 PascalCase `Test/` 并满足 `Data/Test/` 规则。`Data/Test/` 一旦出现，必须递归包含至少一个普通文件。

`Config/`、`Data/`、`Data/Test/` 内允许普通目录和普通文件，不允许符号链接或特殊文件。每个被覆盖目录必须至少有一个直接子项，且后代不得出现空目录。扫描器检查文件类型、符号链接和空目录，不赋予内部名称结构语义。

`Bin/` 表达模块二进制文件集合。一旦出现，必须至少包含一个普通文件。`Bin/` 内只允许普通文件：不允许目录、符号链接或特殊文件。扫描器不解析 `Bin/` 内容，不根据扩展名判断二进制格式，也不把 `Bin/` 文件名解释为结构路径段。`Bin/` 不承载第三方本体目录；供应模块第三方本体进入直接自由余项目录，交付或缓存的二进制载体进入 `Bin/`。

## 供应封装

供应项目用于把第三方能力纳入工程结构。供应项目是直接位于 `Vendor/` 工作区下的项目。供应模块是供应项目的 Main 模块或 Package 模块。项目路径中处于 Vendor 支配下但直接父工作区不是 `Vendor/` 的项目，不因此成为供应项目；这些项目的模块也不因此成为供应模块。

每个第三方本体必须作为目录放在供应模块的直接自由余项中。供应模块可以没有第三方本体目录。当供应模块直接子项位置出现自由余项目录时，该目录一律按结构位置分类为第三方本体目录；扫描器不验证其业务语义上是否真实承载第三方本体。供应模块直接自由余项普通文件只是普通材料，不是第三方本体。

第三方本体目录只接受自由余项载体验证，不接受递归工作区、项目、模块、源码、测试、数据、不变量或二进制结构识别。其中的保留名只是普通文件系统名称。目录型第三方发行包属于第三方本体目录，不进入 `Bin/`。

供应模块的标准结构用于封装第三方本体：

- `Src/` 承载供应能力的模块表面、Application 契约、Adapter 封装与 Boot 组合。
- `Test/` 承载封装验证过程。
- `Config/` 承载封装不变量。
- `Data/` 承载样本、报告和过程产物。
- `Bin/` 承载二进制文件。

其他模块依赖供应能力时，依赖目标是可依赖供应模块，不是第三方本体目录。Import 文件名只映射到供应模块根目录，不包含第三方本体目录名或内部封装细节。当前模块依赖自己模块 `Vendor/` 下的可依赖供应模块时，Import 文件名映射到该供应模块根目录。当前模块依赖另一个模块时，即使那个目标模块内部再依赖自己的供应模块，当前模块的 Import 文件名仍只映射到那个目标模块根目录。

## 环境与依赖解析边界

环境解析机制是语言运行时与包管理器解析依赖的技术手段，例如 `.venv` 与 `site-packages`、`node_modules` 与 hoisting、composer autoload、`GOPATH`、classpath、模块解析路径。它只让某个第三方本体能被解析到，不是结构通道，不授予结构许可。能力由结构位置授予，不由环境可解析性授予。

环境解析是扁平的、全局的、无视模块边界的。第三方本体一旦进入某个可被全局解析的环境，就可能被 `Domain/`、`Application/`、`Adapter/`、`Boot/` 的任意位置直接引用，绕过 `Src/Import/` 边界，违反模块内依赖拓扑，使第三方能力从未经治理的位置漏入内层。本节封闭这条后门，使第三方能力只能经结构边界进入。

### 第三方能力唯一入口

第三方运行时能力只经供应封装进入结构，并与产品内模块走同一条 Import 链；供应模块本身就是模块。第三方本体被供应模块结构性拥有的封装规则、第三方本体目录分类、以及 Import 文件名只映射到供应模块根目录，均由《供应封装》权威给出。下图是能力进入流水线，不是依赖图；`==>` 表示能力流入下游或被下游暴露，方向与全文 `->`（依赖于）相反，故本框不断言任何依赖边。

```text
第三方本体目录（供应模块的直接自由余项目录）
  ==> 供应模块 Adapter 封装（唯一可引用原始本体的位置）
  ==> 供应模块 Application 公开契约与 Src/Boot 运行表面（公开表面）
  ==> 消费模块 Src/Import/<encoded_target>.<ext> 纯绑定
  ==> 消费模块 Src/Adapter/Out/Module/**
  ==> 消费模块 Src/Application/Port/Out/**
```

规则：

- 第三方本体必须先被某个供应模块结构性拥有，其他模块才能依赖它表达的能力。
- 只有拥有该本体的供应模块 `Adapter/` 可以引用原始第三方本体；该供应模块的 `Domain/`、`Application/`、`Boot/` 不引用原始本体。
- 引用原始本体只发生在拥有它的供应模块内部，对该本体而言是模块内引用，不跨结构边界。
- 其他模块取用第三方能力时，目标是可依赖供应模块的公开表面（经目标模块根），经 `Src/Import/` 与 `Adapter/Out/Module/` 落地，与依赖任意模块的口径完全一致。
- 环境让本体能被解析到不等于它可被引用；没有任何位置可以用环境可解析性替代这条链。
- 供应工作区只在模块层出现，不存在项目级 Vendor（见《工作区》表）。被多个模块共享的第三方能力（含 Node、Python 等运行时的共享库这类环境支持）由一个 Package 模块经其模块级 `Vendor/` 拥有，并经正常模块依赖（Main 依赖同项目 Package、Package 依赖同项目 Package）共享给项目下诸多模块。

### 安装与解析拓扑

- 安装与解析拓扑不跨模块边界扁平化；不存在把第三方本体 hoist 成全结构可解析的全局环境。
- 第三方本体归拥有它的供应模块，其解析闭包局部化到该供应模块，不向同结构其他模块外溢。
- 使用包管理器时，包管理器是该供应模块的构建细节，不是全结构共享的能力池。
- 环境解析无法在运行时被完全限制时，残余缺口由语言级工具构造性封闭：禁止任何源码文件直接引用第三方本体，唯一例外是拥有该本体的供应模块 `Adapter/` 对自身本体的引用；跨模块语言级引用必须经生成的 `Src/Import/` 绑定，不得直连其他模块内部。

### 工具链与构成依赖

- 开发与构建工具链不是模块构成依赖，处于构成模型之外，等同操作系统与编译器前提，包括编译器、测试运行器、语言级 linter、打包器和格式化器；其配置文件按自由余项或 `Config/` 处理，不进入依赖图。
- 运行时构成依赖是被任一模块 `Src/**` 源码文件引用、以实现该模块对外表面所依赖行为的第三方库，属第三方运行时能力，必须经供应封装与 Import 链进入，不由环境直接引用。
- 归类判据按引用位置与角色机械判定，可由语言级工具直接执行：第三方本体被任一模块 `Src/**` 源码文件引用即运行时构成依赖，必须走链；只作为对代码进行编译、测试、lint、格式化或打包的工具被调用、且不被任何模块 `Src/**` 源码文件引用的第三方本体属工具链，处于构成模型之外。
- 同一第三方本体既被某模块 `Src/**` 源码文件引用、又被工具链调用时，按更严格的一侧归类为运行时构成依赖，必须走链；该优先级消除同一本体多用途时的归类二义，使归类只取决于是否存在 `Src/**` 源码引用。

### 强制归口

- 结构扫描器不读取语言级 Import 语句，本节边界主要由语言级工具与局部化的安装/解析拓扑构造性强制。
- 结构扫描器仍强制第三方本体只作为供应模块直接自由余项目录存在、只接受载体验证、不进入依赖图，并强制跨模块结构依赖只经 `Src/Import/` 表达。
- "跨模块语言级引用必须经 `Src/Import/` 绑定"的唯一例外是脚本项目对其调用目标模块公开表面（`Src/Boot` 运行表面与 Application 公开契约）的非构成性平台级调用，该例外由《脚本调用边界》权威定义。
- 本节边界进入依赖结构闭合与环境与依赖解析闭合。

## 可依赖模块与依赖图

合法模块是从产品工作区输入根到模块根的路径能经过工作区、项目、模块角色空间、模块边界合法定位，且模块自身结构闭合的模块。合法定位只关心路径边界身份；祖先路径之外的兄弟错误不会移除模块身份。

可依赖模块是在合法模块基础上拥有非空公开表面的模块：至少一个合法源码文件落在 `Application` 公开契约子节（`Port/In`、`Entry`、`Command`、`Query`、`Result`、`Dto`、`Error`）之一，或存在合法 `Src/Boot`。公开表面为空的合法模块既无 `Application` 公开契约子节文件、也无合法 `Src/Boot`：任何被填充的能力位置（Usecase、Adapter、`Port/Out`、Import）都经《源码结构总则·模块三分类与运行性蕴含》的位置蕴含强制带出 `Src/Boot`，从而公开表面非空，故空公开表面与这些能力位置互斥。因此这类模块的 `Src/`（若存在）不含任何 `Application` 公开契约子节文件、不含 Usecase、也无 `Src/Boot`（由蕴含进而无 Adapter、`Port/Out`、Import），至多含 `Domain/` 与/或非公开契约且非 Usecase 的非具名 `Application` 源码；模块整体还可含 `Config/`、`Data/`、`Bin/`、内嵌工作区与自由余项，也可整体无 `Src/`。它是纯数据/类型模块（¬Usecase ∧ ¬Adapter）中公开表面为空的子集，仍然结构合法，但不能作为依赖图节点或 Import 目标。

可依赖性锚（公开表面非空）不蕴含运行性锚（有合法 `Src/Boot`）：仅含 `Entry`、`Command`、`Query`、`Result`、`Dto`、`Error` 这类纯契约/数据公开子节文件、而无 Usecase 与 `Src/Boot` 的纯数据/类型模块，可依赖却不可运行（`Entry` 是零装配的纯契约门面，不蕴含 Usecase 或 `Src/Boot`；`Port/In` 则不在此列：`Port/In ⟹ Usecase ⟹ Src/Boot`，含 `Port/In` 的模块必可运行）。反向则单向蕴含：可运行模块有 `Src/Boot`，`Src/Boot` 即公开表面非空，故可运行模块恒可依赖。两锚因此非对称——可依赖不必可运行，可运行必然可依赖。

模块自身闭合包括直接子项识别、`Src/`、`Test/`、`Config/`、`Data/`、`Bin/`、内嵌工作区、自由余项载体验证、供应模块第三方本体目录分类，以及《源码结构总则·模块三分类与运行性蕴含》的位置蕴含。它不包含跨模块 Import 反解、依赖口径校验或 Package 环检测。

### Main 依赖规则

```text
Main Module -> same project Package Module
```

规则：

- Main 模块永远不直接依赖 Main 模块。
- 同一 `Main/` 角色空间中的 Main 之间没有直接依赖关系。
- 不同项目的 Main 之间没有直接依赖关系。
- 无论 Main 模块所在项目属于哪种工作区，Main 的直接构成性依赖只指向同项目 `Package/` 下的 Package 模块。
- Main 模块不能直接依赖本模块 `Vendor/`、其他产品项目 Package 或任何 Main 模块。
- Main 需要供应能力时，先由同项目 Package 表达供应依赖，再由 Main 依赖该 Package。
- Vendor 支配不放宽 Main 规则；处于 Vendor 支配下的 Main 仍然只依赖自己项目的 Package。
- Main 到 Main 的交互通过运行边界、协议、配置、工具操作或外部系统表达。

### Package 依赖规则

```text
Package Module -> same project Package Module
Package Module -> this Module direct Vendor Workspace project Main/Package Module
non-Vendor-governed Package Module -> other product Workspace project Package Module
```

规则：

- Package 可以依赖同项目 Package，但不能依赖自身。
- Package 可以依赖本模块 `Vendor/` 下直接供应项目中的可依赖 Main/Package 模块。
- 不处于 Vendor 支配下的 Package 可以依赖其他产品工作区直接项目中的 Package 模块。该规则只适用于外层工作区 profile。
- 当前产品项目根 profile 下，"其他产品工作区直接项目 Package"目标集合为空。
- 处于 Vendor 支配下的 Package 不能依赖任何产品工作区项目模块。
- 产品工作区项目规则只覆盖外层工作区 profile 中扫描输入根下的直接项目，不包含内嵌工作区项目，并且只适用于非当前产品项目。
- 这里的"当前项目"指当前 Package 模块直接所在项目，不是宿主项目或外层祖先项目。
- 该规则不能用于依赖当前项目模块，也不能用于依赖任何产品项目 Main 模块。
- 直接供应项目指 `Vendor/` 工作区的直接子项目。
- 供应项目内部再次嵌套的 `Tool/`、`Script/`、`Docs/`、`Vendor/` 工作区中的项目，不属于这条 Vendor 依赖规则的目标。
- Package 不能依赖自己的祖先模块。
- 祖先模块是从产品工作区根到当前模块根的结构路径上已经经过且不是当前模块自身的模块根；非模块路径前缀不是祖先模块。

### Vendor 支配

Vendor 支配是路径性质。从产品工作区输入根到某个项目目录的结构路径中，只要经过任意 `Vendor` 工作区，该项目就处于 Vendor 支配下。其后代内嵌工作区项目也继续处于 Vendor 支配下，即使经过嵌套的 `Tool`、`Script`、`Docs` 或 `Vendor` 工作区。是否 Vendor 支配不只看直接父工作区名。

### Package 环检测

所有可依赖 Package 之间的直接 Package-to-Package 构成性依赖边必须无环。环检测在产品工作区结构投影得到的全量可依赖 Package 节点集合上执行，包含没有入边或出边的节点。

边只来自合法 Package -> Package Import：

- 源和目标都是可依赖 Package。
- Import stem 合法且 canonical。
- 目标存在。
- Package 依赖规则允许。
- Import 文件没有累计错误。

重复、非 canonical、目标不可依赖、依赖违规或其他带 Import 错误的文件都不生成环检测边。环检测覆盖同项目 Package、Vendor 目标 Package 和产品工作区目标 Package。Package -> Main 与 Main -> Package 边不进入 Package 环检测。

环错误按强连通分量报告。节点数大于一的每个分量生成一个 Package 环错误，载荷包含该分量内全部 Package 节点和全部内部合法 Package -> Package 边，并按 canonical 模块根路径数组排序。结构非法 Package、合法但不可依赖 Package、以及 Import 目标不可依赖 Package 都不进入环检测节点；它们的结构错误或 Import 错误先于环检测成立。

## 扫描阶段与识别顺序

结构识别从产品工作区根路径开始，并只沿结构候选边界继续。候选用于诊断和定位；合法结构节点用于构造可依赖模块集合与依赖图。候选不等于合法。

结构身份与闭合结果分离，这是身份与闭合关系的权威原则，其余章节引用此处。身份说明一个文件系统项能否作为工作区、项目、模块角色空间、模块或模块保留项被定位并继续扫描。闭合说明其直接内容和后代内容是否符合规则。非法兄弟项会让父容器产生闭合错误，但不取消父容器作为路径边界的结构身份，也不取消同级合法子树的身份。非法候选自身不成为合法节点，也不继续扫描后代。

扫描阶段：

1. 第一阶段：执行结构候选投影、合法结构投影和载体验证，得到工作区候选、项目候选、模块角色空间候选、模块候选、模块保留项候选、内嵌工作区候选、自由余项、第三方本体目录、合法模块和可依赖模块。
2. 第二阶段：反解 `Src/Import/`，生成跨模块结构依赖错误和合法依赖边。
3. 第三阶段：只在第二阶段生成的合法 Package -> Package 边上执行 Package 环检测，不另行执行额外依赖闭合算法。

第二、第三阶段发现的跨模块错误不反向改变第一阶段得到的合法模块身份或可依赖模块身份。

按位置识别：

- 产品项目根 profile 输入根：先排除固定过程载体，再把输入根自身作为根产品项目 `@rootProject` 执行项目扫描。输入根直接子项按项目直接子项规则识别：`Main/`、`Package/` 是模块角色空间，`Tool/`、`Script/`、`Docs/` 是内嵌工作区，`Vendor/` 在项目直接子项位置永远违规，其他非排除项是自由余项。输入根 basename 不参与结构路径段规则、模型保留词检查或 canonical Import 编码。
- 产品工作区：只检查直接子项。每个直接子项先形成产品项目候选。普通目录、名称符合结构路径段规则且不使用模型保留词的候选成为合法产品项目并继续扫描。非目录、符号链接、点目录、非法名称、保留名目录都是工作区违规，保留为非法项目候选，不扫描后代。
- 内嵌工作区：使用与产品工作区相同的直接项目候选规则，但项目语义由该工作区决定。
- 项目：只检查直接子项。`Main/`、`Package/` 形成模块角色空间候选；若为普通目录，则成为合法定位的角色空间，其内容错误记为角色空间闭合错误。`Tool/`、`Script/`、`Docs/` 形成内嵌工作区候选；若为普通目录，则成为合法定位的内嵌工作区，其内容错误记为工作区闭合错误。`Workspace/` 与 `Vendor/` 违规。保留名大小写变体违规，并按对应保留位置保留为非法候选。其他直接子项识别为自由余项，停止结构递归，再做载体验证。项目直接子项中的一个错误只影响该子项及其可达后代，不自动使同项目其他合法定位模块失去身份。
- 模块角色空间：只检查直接子项。每个直接子项先形成对应角色的模块候选。普通目录、名称合法且不使用模型保留词的候选进入模块扫描；模块自身闭合后成为合法模块。非目录、符号链接、点目录、非法名称、保留名目录都是角色空间违规，保留为非法模块候选，不成为合法模块，不扫描后代。Import 反解最终落到这些非法模块候选时，错误分类为 Import 目标模块结构非法。
- 模块：只检查直接子项。`Src/`、`Test/`、`Config/`、`Data/`、`Bin/` 形成模块保留项候选；载体类型符合时成为合法定位的保留项，其内容错误记为模块闭合错误。`Tool/`、`Script/`、`Docs/`、`Vendor/` 形成绑定当前模块的内嵌工作区；若为普通目录则继续扫描。`Workspace/` 违规。保留名大小写变体违规，并按对应保留位置保留为非法候选。其他直接子项识别为自由余项，停止结构递归，再做载体验证。供应模块中，直接自由余项目录同时分类为第三方本体目录；直接自由余项普通文件仍只是普通自由余项文件。
- `Src/`：只检查直接子项是否属于 `Boot/`、`Import/`、`Domain/`、`Application/`、`Adapter/`。只递归进入 `Boot/`、`Domain/`、`Application/`、`Adapter/` 作为源码目录。`Import/` 只放 Import 文件。
- `Test/`：以实际结构源码文件集合生成期望测试文件，再检查一一镜像并拒绝额外内容。
- `Config/`：递归执行数据载体验证，并要求至少一个普通文件。
- `Data/`：先处理直接子项 `Test/` 的测试数据保留项规则，再递归执行载体验证；`Data/Test/` 内部的 `Test` 名称不具结构语义、按普通数据载体处理。
- `Bin/`：只检查直接子项；全部必须是普通文件，且目录不能为空。

不得进入自由余项递归寻找保留项。目录是否具有结构语义，只由所在位置和直接父对象决定。

合法模块身份只由第一阶段确定。模块要成为合法模块，必须满足：从当前 profile 的扫描输入根到模块根的每个结构边界都已合法定位；模块自身结构闭合。合法定位不要求所有祖先边界自身闭合，也不要求祖先容器所有兄弟项无错误。可依赖模块身份进一步要求公开表面非空（`Application` 公开契约子节之一或 `Src/Boot`）。

第二阶段 Import 反解有两个源集合：

- 诊断反解源集合：能确定模块 `<ext>`（census 可判定）且能扫描 `Src/Import/` 的模块候选，即使它们因缺测试镜像、自由余项载体验证失败或其他自身闭合错误而不是合法模块，也可以产生 Import 诊断。
- 合法依赖边生成源集合：仅可依赖模块。

只有源模块属于合法边生成源集合、目标模块可依赖、Import 文件没有累计错误且 Main/Package 依赖规则通过时，才生成合法依赖边。

## 闭合要求

闭合要求是各结构维度的判定清单。每一维的内容规则由其权威主章给出，本章只点名引用并补充该维独有的闭合性质；身份与闭合分离原则由《扫描阶段与识别顺序》给出，闭合错误不取消相应边界身份与同级合法子树身份。

### 工作区闭合

按《工作区》判定：工作区直接子项全部是项目目录，产品工作区只出现在扫描输入根，`Tool`/`Script`/`Docs` 工作区只出现在项目或模块直接子项位置，`Vendor` 工作区只出现在模块直接子项位置。工作区闭合错误不取消工作区边界身份与同一工作区下其他合法定位项目的身份。

### 项目闭合

按《项目》判定：模块只出现在 `Main/` 或 `Package/` 下；内嵌工作区只出现在项目或模块直接子项位置，其中 `Vendor/` 只在模块直接子项位置；模块角色空间与内嵌工作区按需出现，一旦出现必须包含对应合法定位的结构对象；项目目录不能为空。项目闭合错误不取消项目边界身份与同一项目下其他合法定位模块的身份。

### 模块闭合

按《模块》及各保留项专章判定：`Src/`、`Test/`、`Config/`、`Data/`、`Bin/` 与内嵌工作区边界清晰；`Src/` 与 `Test/` 的共现与镜像由《测试结构》给出，共现锚是"`Src` 含至少一个合法源码或 Import 文件"；`Config/`、`Data/`、`Bin/` 由《Config、Data 与 Bin》给出；模块目录不能为空。模块还须满足《源码结构总则·模块三分类与运行性蕴含》的位置蕴含闭合：`Usecase ⟹ Src/Boot`、`Src/Boot ⟹ Usecase`、`Adapter ⟹ Src/Boot`、`Adapter ⟹ Usecase`、`Port/In ⟹ Usecase`、`Port/Out ⟹ Adapter/Out`、`Import ⟹ Adapter/Out/Module`，违反任一记模块闭合错误。模块闭合错误使该模块不能成为合法模块，但保留其模块候选诊断身份。

### 源码闭合

按《源码结构总则》《Src/Boot/ 组合根》《Import/ 纯绑定边界》及 `Domain/`/`Application/`/`Adapter/` 专章与《依赖规则优先级》判定：`Src/` 内只有 `Boot/`、`Import/`、`Domain/`、`Application/`、`Adapter/`（皆区域目录，无直接普通文件）；各区符合其依赖边界。结构扫描器与语言级工具的职责分工见《验证注意事项》末段；语言级补充验证不得改变结构扫描得到的模块依赖图。

### 依赖结构闭合

跨模块构成性依赖只经 `Src/Import/` 表达（《Import/ 纯绑定边界》），并满足《可依赖模块与依赖图》的 Main/Package 依赖规则、Vendor 支配与 Package 环检测。Import 文件授予的目标是目标模块公开表面（`Application` 公开契约 ∪ 目标 `Src/Boot`，经目标模块根）。第三方本体目录不进入依赖图，可依赖供应模块经其公开表面进入依赖图（《供应封装》）。脚本对目标模块公开表面的平台级调用是非构成性边界，不进入依赖图、Main/Package 依赖规则或 Package 环检测（《脚本调用边界》）。

### 脚本闭合

按《脚本调用边界》判定：脚本项目只作为调用入口，不成为目标模块 `Src` 的组成部分；绑定模块的脚本只调用该模块 `Src/Boot` 运行表面（createApp/RunnableApp）与 Application 公开契约，项目级脚本优先调用所在项目 Main 模块表面；脚本对公开表面的调用是非构成性平台级调用，不经 `Src/Import/`、不生成依赖边，且不能穿透目标模块内部目录或让目标模块反向依赖脚本。

### 供应封装闭合

按《供应封装》判定：供应项目、供应模块、可依赖供应模块和第三方本体目录都由结构位置判定；供应项目是直接位于 `Vendor/` 下的项目，供应模块是供应项目的 Main/Package 模块，可依赖供应模块是可依赖的供应模块；供应模块直接自由余项目录是第三方本体目录，只接受载体验证，不进入递归结构识别或依赖图。可依赖供应模块经其公开表面（`Application` 公开契约 ∪ `Src/Boot`）进入依赖图。依赖图节点只来自可依赖模块。

### 环境与依赖解析闭合

按《环境与依赖解析边界》判定：第三方运行时能力只经供应模块第三方本体、供应模块 `Adapter/` 封装、供应模块公开表面（`Application` 公开契约 ∪ `Src/Boot`）以及消费模块 `Src/Import/` 到 `Adapter/Out/Module/` 链进入；环境可解析性不授予结构许可；安装与解析拓扑不跨模块边界扁平化，第三方本体解析闭包局部化到拥有它的供应模块。结构扫描器强制第三方本体的供应封装位置、载体验证与跨模块 Import 表达；原始本体的语言级引用边界、经环境直接引用原始本体的禁止与解析局部化由语言级工具与局部化解析构造性强制；开发与构建工具链处于构成模型之外，不进入依赖图。

### 载体闭合

载体闭合要求真实文件系统中的目录和文件能被结构规则识别、解释和回读。完成结构投影后，回读结果应能重新得到相同的工作区、项目、模块、源码、测试、数据、不变量、二进制文件、内嵌工作区和自由余项边界。

## 演化信号

以下现象不是局部小问题，而是模块分裂、聚合或边界重画信号：

- `Application` 公开契约子节需要定义装配或运行内容：应移入 `Src/Boot/`；反之 `Src/Boot/` 膨胀出业务或契约类型：应移回 `Application/` 或 `Domain/`。
- 公开契约或公开表面需要泄漏 `Adapter/`：启动或运行装配被错误暴露到表面。
- 公开契约或公开表面需要泄漏 `Domain/`：领域对象正在跨模块泄漏。
- 公开表面需要穿透 `Import/`：外部模块能力正在穿透公开表面。
- `Src/Boot/` 直接读取平台输入（命令行、HTTP 监听端口、进程环境、部署平台状态）：组合根越界成了启动器，应交给绑定 `Script/` 工作区。
- `Src/Boot/` 直接依赖 `Domain/`：绕过 Application contract。
- `Src/Boot/` 接收具体 Adapter 注入而非 `env`：模块自组合被破坏，`env` 应只携配置、共享基础设施句柄或数据。
- `Import/` 文件需要转换或定义本地类型：适配逻辑应进入 `Adapter/Out/Module/` 或 `Adapter/Mapper/`。
- `Application/` 需要依赖 `Import/`：跨模块能力没有被抽象成 `Port/Out`。
- `Application/` 需要依赖 `Adapter/`：用例正在依赖技术实现。
- `Adapter/` 需要依赖 `Domain/`：技术实现绕过 Application contract。
- `Adapter/Out/Module/` 文件数量快速增长：当前模块依赖外部能力过多，可能职责过宽。
- `Domain/` 规则和模型快速膨胀：业务概念可能需要拆成多个 Package。
- `Application/Port/In/` 过宽：模块公开能力边界不清晰。
- `Application/Port/Out/` 过宽：模块外部能力需求过散，可能需要新增 Package 或供应封装。
- 脚本需要调用多个 Package 内部对象：应建立或调整 Main 模块表面。

## 验证注意事项

工具体系使用稳定诊断和记录 payload 字段：

```text
recordId
recordKind
methodVersion
stateVersion
rootProfile
rootProjectId
excludedRootEntries
operationKind
entityId
entityKind
projectId
moduleId
moduleRole
vendorGoverned
sameProjectScope
pathFromRoot
canonicalPathSegments
importStem
findingId
findingKind
severity
ruleId
message
sourceRecordIds
```

### payload 字段 schema

payload 字段按下表给出机器可判定的类型、必填性、可空条件、取值空间与排序。枚举字段的取值空间封闭、有限：实现必须为本文件相应章节定义的每个类别选定一个稳定标识符，并跨运行保持稳定；标识符文法是 `[A-Za-z][A-Za-z0-9]*`。标识类字段是跨运行稳定、对同一逻辑对象唯一的不透明串。数组字段不适用时取空数组，非数组可空字段不适用时取 `null`。

正文按结构维度命名的工作区闭合错误、项目闭合错误、角色空间闭合错误、模块闭合错误、源码闭合错误同属 `findingKind` 的单一类别"结构闭合错误"，按 `entityKind` 与 `ruleId` 区分定位，不各自另立 `findingKind`；唯一性冲突、模块扩展名冲突、各 Import 诊断类别、测试保留项缺失、测试镜像缺失、测试镜像多余、测试镜像不可判定、载体验证失败、Package 环错误各自独立成 `findingKind` 类别。《闭合要求》列出的工作区、项目、模块、源码、依赖结构、脚本、供应封装、环境与依赖解析、载体各闭合维度都不另立新 `findingKind`：其结构扫描器可判定的违规归入上述既有类别（结构闭合错误、唯一性冲突、模块扩展名冲突、各 Import 诊断、测试保留项缺失与测试镜像各类、载体验证失败、Package 环错误），其委派给语言级工具构造性强制的边界（脚本对公开表面的调用边界、源码语言级 Import 方向、经环境直接引用原始本体的禁止、解析局部化等，见《验证注意事项》末段）由语言级工具自有诊断承载，不进入本结构扫描器 `findingKind` 枚举。这是正文诊断措辞与 `findingKind` 枚举之间映射的权威定义，`findingKind` 行与各闭合维度章节引用此处。

| 字段 | 类型 | 必填性 | 取值空间与可空条件 |
| --- | --- | --- | --- |
| `recordId` | 标识符 | 每条记录必填 | 全局唯一、跨运行稳定，非空 |
| `recordKind` | 枚举 | 每条记录必填 | 本文件产出的记录类别全集（结构实体记录、依赖边记录、finding 记录），封闭有限；Import 诊断不是独立记录类，以 finding 记录产出（见下文字段约定） |
| `methodVersion` | 版本标识 | 每条记录必填 | 标识产出该记录所用的方法与规范版本 |
| `stateVersion` | 版本标识 | 每条记录必填 | 标识被扫描结构状态的快照版本 |
| `rootProfile` | 枚举 | 每条记录必填 | 封闭取值：外层工作区 profile、产品项目根 profile |
| `rootProjectId` | 标识符 | 每条记录必填 | 产品项目根 profile 下固定 `@rootProject`；外层工作区 profile 下，隶属某产品项目的记录取相应产品项目标识，定位工作区根或跨项目的工作区级记录取固定哨兵 `@rootWorkspace` |
| `excludedRootEntries` | 名称数组 | 每条记录必填 | 可为空数组；产品项目根 profile 下取值只能是 `.git`、`.temp`、`CLAUDE.md` 的子集；按字典序排序 |
| `operationKind` | 枚举 | 每条记录必填 | 本文件定义的操作与阶段类别全集（结构候选投影、合法结构投影、载体验证、Import 反解、canonical 检查、重复 Import 检查、依赖规则检查、Package 环检测），封闭有限；扩展名 census 与模块扩展名冲突判定、源码 stem 唯一性、测试镜像检查等第一阶段合法结构判定均归入"合法结构投影" |
| `entityId` | 标识符 | 定位结构实体的记录必填，否则取 `null` | 定位到的结构实体的稳定唯一标识 |
| `entityKind` | 枚举 | 定位结构实体的记录必填，否则取 `null` | 本文件定义的实体类别全集（工作区、项目、模块角色空间、模块、模块保留项、内嵌工作区、源码目录、源码文件、Import 文件、测试目录、测试文件、自由余项、第三方本体目录），封闭有限；`Config/`、`Data/`（含 `Data/Test/` 子树）、`Bin/` 内部内容与自由余项内部内容不另立内部载体的实体类别，其载体验证失败定位到所属的模块保留项或自由余项实体，由 `pathFromRoot` 给出精确载体路径（`Data/Test/` 的测试数据结构语义只影响其识别与闭合规则，不改变其内部载体仍归 `Data/` 模块保留项定位）|
| `projectId` | 标识符 | 实体隶属某项目时必填，否则取 `null` | 根项目为 `@rootProject` |
| `moduleId` | 标识符 | 实体隶属某模块时必填，否则取 `null` | 定位到的模块的稳定唯一标识 |
| `moduleRole` | 枚举 | 模块相关记录必填，否则取 `null` | 封闭取值：`Main`、`Package` |
| `vendorGoverned` | 布尔 | 定位项目或模块的记录必填，否则取 `null` | 该实体是否处于 Vendor 支配下 |
| `sameProjectScope` | 布尔 | 依赖相关记录必填，否则取 `null` | 该依赖关系是否处于同一项目作用域 |
| `pathFromRoot` | 路径段数组 | 定位结构实体的记录必填，否则取空数组 | 从扫描输入根到该实体的真实路径段，按出现顺序 |
| `canonicalPathSegments` | 路径段数组 | 定位模块或项目级实体的记录必填，否则取空数组 | 按《Import 边界与文件编码》计算；产品项目根 profile 下不含输入根 basename 与虚拟项目名 |
| `importStem` | Import 编码串 | 定位 Import 文件实体的记录、依赖边记录、`findingKind` 属 Import 诊断类别的 finding 记录必填，否则取 `null` | 该 Import 文件的完整编码 stem；依赖边记录取生成该边的 canonical Import 编码 |
| `findingId` | 标识符 | finding 记录必填，否则取 `null` | 全局唯一、跨运行稳定 |
| `findingKind` | 枚举 | finding 记录必填，否则取 `null` | 本文件正文定义的诊断类别全集（结构闭合错误、唯一性冲突、模块扩展名冲突、Import 越界、Import 目标缺失、Import 路径非法、Import 目标非模块、Import 目标模块结构非法、Import 自依赖、Import 祖先依赖、Import 目标不可依赖、Import 依赖违规、Import stem 唯一性错误、重复 Import、非 canonical Import、测试保留项缺失、测试镜像缺失、测试镜像多余、测试镜像不可判定、载体验证失败、Package 环错误），每类对应一个稳定标识，封闭有限 |
| `severity` | 枚举 | finding 记录必填，否则取 `null` | 封闭取值；本文件定义的全部诊断 severity 均为 `error` |
| `ruleId` | 规则标识符 | finding 记录必填，否则取 `null` | 定位到产生该 finding 的本文件规则的稳定标识，与 `findingKind` 对应 |
| `message` | 文本 | finding 记录必填，否则取 `null` | 人类可读诊断说明，不参与机器判定 |
| `sourceRecordIds` | recordId 数组 | finding 记录必填，否则取空数组 | 该 finding 依据的来源记录 id 集合，按 `recordId` 字典序排序 |

每类记录携带字段约定：

- 每条记录必带 `recordId`、`recordKind`、`methodVersion`、`stateVersion`、`rootProfile`、`rootProjectId`、`excludedRootEntries`。
- 定位某结构实体的记录必带适用的定位字段：`entityId`、`entityKind`，以及该实体可定位到的 `projectId`、`moduleId`、`moduleRole`、`vendorGoverned`、`pathFromRoot`、`canonicalPathSegments`；不适用的定位字段取 `null` 或空数组。
- 每条 finding 记录必带 `findingId`、`findingKind`、`severity`、`ruleId`、`message`、`sourceRecordIds`，以及定位该 finding 所涉实体的定位字段。
- Import 诊断以 finding 记录产出，承载诊断类别的字段是 `findingKind`：其 `recordKind` 取 finding 记录，`findingKind` 取对应 Import 诊断类别（Import 越界、Import 目标缺失、Import 路径非法、Import 目标非模块、Import 目标模块结构非法、Import 自依赖、Import 祖先依赖、Import 目标不可依赖、Import 依赖违规、Import stem 唯一性错误、重复 Import、非 canonical Import 之一）。它定位触发诊断的 `Src/Import/` Import 文件实体（`entityKind`=Import 文件），并必带 `importStem` 承载该 Import 文件的编码 stem；`findingId`、`severity`、`ruleId`、`message`、`sourceRecordIds` 等 finding 字段按上一条携带。
- 依赖边记录定位生成该边的 `Src/Import/` Import 文件实体（`entityKind`=Import 文件），其 `entityId`、`moduleId`、`moduleRole`、`vendorGoverned`、`pathFromRoot`、`canonicalPathSegments` 取该 Import 文件所在的源端模块值，并必带 `importStem`（该 Import 文件的 canonical 编码，相对源端模块根编码目标端模块）与 `sameProjectScope`。目标端模块及其角色由源端 `canonicalPathSegments` 叠加 `importStem` 按《Import 边界与文件编码》反解唯一恢复，故源端与目标端两个模块均由记录自身判定。`findingId` 等 finding 字段取 `null`，`sourceRecordIds` 取空数组。
- 多记录输出按 `recordKind`、`canonicalPathSegments` 字典序、`entityId`、`findingKind`、`recordId` 排序。可空排序键 `entityId` 与 `findingKind` 在比较中以 `null` 恒先于所有非空值定序；`canonicalPathSegments` 不适用时取空数组，按字典序与非空数组定序，不出现 `null`。末键 `recordId` 全局唯一、跨运行稳定，使该排序键构成确定全序：当 `recordKind`、`canonicalPathSegments`、`entityId`、`findingKind` 在共位同类记录上全等时（例如同一模块同时违反 `Port/In ⟹ Usecase` 与 `Port/Out ⟹ Adapter/Out`，产出两条 entityId、findingKind 全等的结构闭合错误 finding；又如 Package 环错误 finding 因跨强连通分量多节点而 `entityId` 取 `null`，与同 `recordKind`、同空 `canonicalPathSegments` 的载体验证失败 finding 共位时，其 `entityId` 的 `null` 按上述固定位次先于非空值），仍由 `recordId` 唯一定序，故同一实现的输出次序跨运行确定。排序键 `recordKind`、`findingKind` 等枚举标识符与 `recordId` 由实现各自选定、只保证跨运行稳定（见本节首段与 `recordId` 行），不跨实现统一，故跨实现的字节级次序不在本节声称范围内。

当前产品项目根 profile 中：

- `rootProjectId` 固定为 `@rootProject`。
- `canonicalPathSegments` 不包含输入根 basename 和虚拟项目名。
- `excludedRootEntries` 只能包含 `.git`、`.temp`、`CLAUDE.md`。

工具运行产生的状态、记录和报告只能写入合法模块的 `Data/` 目录；不得在根目录新增开放式过程载体（口径见《核心模型》）。

结构扫描器负责目录、文件、命名、扩展名 census、镜像、Import 编码、依赖规则和环检测。语言级工具负责补充验证 `Src/Boot` 组合根契约（`createApp(env) -> RunnableApp`、`env` 不含具体 Adapter 或 Port/Out 实现、Boot↛Domain/Import/其他模块）、`Import` 纯绑定、源码依赖方向、脚本调用边界、具体语言 Import 语句边界和环境与依赖解析边界。此分工是结构扫描器与语言级工具职责划分的权威陈述，其余章节引用此处。
