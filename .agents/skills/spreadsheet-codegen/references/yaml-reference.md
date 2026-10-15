# YAML 字段完整参考

本文是自包含的字段级权威定义 —— 本 skill 不依赖任何外部文档。
需要"为什么这么设计 / 什么时候别用"的判断，看 `engine-preflight.md`、`excel-layout.md`、
`pitfalls.md`；这里只讲**写什么、默认值是什么、报什么错**。

---

## 1. 根节点

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `version` | int | 否 | `1` | 必须 ≥ 1 |
| `extends` | list[str] | 否 | `[]` | 先合并这些 YAML，**路径相对本文件**解析，见 §7 |
| `excel` | mapping | 否 | 见 §2 | |
| `variables` | mapping | 否 | 空 | `global` / `local` / `group` |
| `templates` | list | **是** | — | 至少一个 |
| `asserts` | list[str] | 否 | `[]` | 跨变量校验，对每个 Case 求值，见 §4 |

YAML 解析**不容忍同键重复**：同一个映射里写两次同名键会按行号报错
（常见于写了两块 `variables:`）。

---

## 2. `excel`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `output` | str | `template.xlsx` | `init` / `render` / `check` / `doctor` 默认用的工作簿 |
| `template_sheet` | str \| null | `Template` | 隐藏参考表（模板原文 + 元信息）；`null` 不生成 |
| `howto_sheet` | str \| null | `HOWTO` | 说明表，**放第一张**；`null` 不生成 |
| `sheets.global` | str | `Global Parameter` | 全局表名 |
| `sheets.local` | str | `Local Parameter` | 局部表名 |
| `sheets.outputs` | list[str] | `["Output"]` | 所有输出表名；模板的 `output_sheet` **必须**在此声明 |
| `local_direction` | `horizontal` \| `vertical` | `horizontal` | **输入**侧 Local 表的工况排布，与模板自己的 `direction` 无关 |

表名限制：≤ 31 字符，不含 `[ ] : * ? / \`；`template_sheet` / `howto_sheet` 不能与
Global / Local / Output 表名冲突（配置阶段就报错）。

### 路径规则（一条，别记混）

- 配置里的相对路径 —— `excel.output`、`template_file`、`{% include %}` 片段 ——
  一律**相对声明它的那个文件**解析。
- 命令行给的 `-o` / `-x` / `--outdir` 相对**当前工作目录**。
- 摘要里一律打印规范化后的**绝对路径**。

---

## 3. `variables.global[]` / `variables.local[]`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `name` | str | **必填** | 必须是 `[A-Za-z_][A-Za-z0-9_]*`；不能用保留名 `case_name` / `template_name` |
| `description` | str | `""` | 写进 Excel 描述列，纯注释 |
| `unit` | str | `""` | **纯文档**：只进批注与 `validate` 清单，**不进生成结果**。要进结果用 `suffix` |
| `default` | any | `""` | 默认值，见 §5.3。**与 `derived` 互斥** |
| `prefill` | bool | `true` | `init` 建表时是否把 `default` 预填进新单元格 |
| `fallback` | bool | 跟 `prefill` | 单元格为空时是否回落 `default` |
| `prefix` | str | `""` | 组合值前缀（写进 Excel 的 Prefix 列，可在表里覆盖） |
| `suffix` | str | `""` | 组合值后缀（**前导空格有意义**） |
| `type` | enum | `auto` | `auto` / `string` / `int` / `float` / `bool` / `raw`，见 §5.1 |
| `derived` | str \| null | `null` | 派生参数：一段表达式，引用同 Case 的 local + global，见 §6 |
| `min` / `max` | number \| null | `null` | 取值约束：数值上下限。**只能给数值类型** |
| `choices` | list \| null | `null` | 取值约束：允许的取值集合，按**文本**比较，写成 Excel 下拉 |
| `pattern` | str \| null | `null` | 取值约束：整串匹配的正则（`re.fullmatch`）。**不会写进 Excel** |
| `allow_blank` | bool | `false` | 声明了约束时是否允许留空 |

**global 还是 local**：所有 Case 共用的值（项目名、版本、主尺度）→ `global`；
每个 Case 不同的值（端口、通道、工况参数）→ `local`。

同名变量在 global 与 local 中重复**允许**（local 覆盖 global，`validate` 给警告）；
**同一作用域内重名直接报错**。三类作用域（含成员表）之间**不能重名**。

> 表里多出来的、YAML 未定义的变量行**允许存在**（按 `auto` 读进上下文）。
> `validate` 会对"模板引用了但 YAML 未定义"给出提示。

---

## 4. `asserts` —— 跨变量校验

单变量约束只能看一列；组合条件（吃水 > 型深、内外压混用）用根级 `asserts`：

```yaml
asserts:
  - "draft.value <= d_tank.value"
  - "0 < rho_tank.value < 1100"
  - "not (kind.value == 'INT' and p_vp.value > 0)"
```

- **对每个 Case 求值**，为假就报错并指名道姓（表、列、Case、表达式）。
- 写法与 `case_filter` **完全一致**：数值比较必须写 `.value`；裸变量是组合值（字符串）。
- 可用 `and` / `or` / `not`、括号、`min()` / `max()` / `abs()` 等。
- 带 `-x` 跑 `validate` 会连值一起查；不带只编译表达式（查语法）。
- `render` / `check` **每次读表都查**。
- 被 `extends` 进来的文件里的 `asserts` **全部保留**（顺序：先被 extends 的在前）。
- 一个 Case 违反多条会全部列出。

---

## 5. 值、类型、前后缀

### 5.1 `type` 与取值转换

| `type` | 行为 | 表里写 | 上下文中 |
| --- | --- | --- | --- |
| `auto`（默认） | 保留 openpyxl 读到的原始类型 | `115200` | `int 115200` |
| `string` | 一律转字符串 | `115200` | `"115200"` |
| `int` | 转 int（允许 `"9600"`、`9600.0`） | `9600` | `9600` |
| `float` | 转 float | `1.5` | `1.5` |
| `bool` | `1/true/yes/y/on` → True；`0/false/no/n/off/空` → False | `true` | `True` |
| `raw` | 同 `auto`，语义上表示"别动它" | 任意 | 原值 |

转换失败报明确错误：`变量 Case1.baud 的值 'abc' 无法转换为 int`。

**文本形态**：整数浮点规范化（`115200.0` → `115200`，超 `1e16` 保留科学计数法）；
布尔输出 `true` / `false`；`None` 输出空串。`{{ x }}`、`{{ x.value }}`、`{{ 340.0 }}`
三条路径形态一致（由 Jinja2 `finalize` 统一施加），做 diff 不会出假差异。

> `type: bool` 在 **Excel 公式模式**里是 `TRUE` / `FALSE`，Python 侧是 `true` / `false`
> —— 已知差异。建议 bool 变量用 `type: string`，或该模板用 `engine: snapshot`。

### 5.2 Prefix / Value / Suffix

每个变量在上下文里是一个 `VarValue`：

```python
VarValue(value="A", prefix="GPIO", suffix="_PORT")
str(v)  # "GPIOA_PORT"   组合值 = prefix + value + suffix
v.value  # "A"            纯值（保留原始类型）
v.prefix  # "GPIO"
v.suffix  # "_PORT"
v.text  # "A"            纯值的字符串形式
v.is_empty  # 值/前缀/后缀全空时为 True
```

模板里的四种写法：

```jinja
{{ port }}          {# GPIOA_PORT —— 组合值 #}
{{ port.value }}    {# A          —— 纯值 #}
{{ port.prefix }}   {# GPIO       #}
{{ port.suffix }}   {# _PORT      #}
```

过滤器 `pvs` / `wrap`（两者完全等价，**只支持快照模式**）：

```jinja
{{ "A" | pvs("GPIO", "_PORT") }}           {# GPIOA_PORT #}
{{ port.value | wrap("GPIO", "_PORT") }}   {# GPIOA_PORT #}
{{ mode.value | pvs("MODE_") }}            {# MODE_TX_RX（suffix 可省略） #}
```

**前后缀是按"变量"配置的，不是按 Case**（Local 表的 C / D 列在变量行上，所有 Case 共用）。
要"不同 Case 不同前缀"，就再加一个局部变量承载前缀，或把完整名字直接填进单元格。

### 5.3 空值语义与回落顺序

回落只看**单元格是不是真的空**，非空值原样使用 —— **首尾空格有意义**：

| 情况 | 结果 |
| --- | --- |
| 单元格留空（真空白） | 用 YAML `default` |
| 单元格只敲了空格 | 视为未填写 → 用 `default` |
| 单元格填了值 | 用单元格值（**原样，不 strip**） |
| Prefix / Suffix 格子留空 | 用 YAML 的 `prefix` / `suffix` |
| Prefix / Suffix 格子非空 | 原样使用，**保留空格** |

所以"值 + 单位"直接用后缀表达：

```yaml
- name: L
  default: 340
  suffix: " m"        # 前导空格是刻意的
```

```jinja
var L = {{ L }};       {# -> var L = 340 m;  而不是 340m #}
```

> 想"清掉" YAML 里的前后缀只能改 YAML —— Excel 里的空格子被视为"未填写"。

### 5.4 `default` 的两种用途：预填 vs 回落

| 用途 | 触发时机 | 关掉它 |
| --- | --- | --- |
| **预填** | `init` 建表时把 `default` 写进新单元格（当提示值） | `prefill: false` |
| **回落** | 读取时单元格为空 → 用 `default` 顶上 | `fallback: false` |

**默认两个都开**（与老版本行为一致）。典型问题场景是"某类型才有的字段"：
银行卡记录本来没有 `url`，清空那格却回落到默认 url，导出的数据里就多了一个不该有的字段，
而且**不报错** —— 这种变量写 `fallback: false`。

| 写法 | 新表里 | 清空后读取时 |
| --- | --- | --- |
| 不写（默认） | 预填 `default` | 回落 `default` |
| `fallback: false` | 预填 `default` | **空** |
| `prefill: false` | **留空** | **空**（`fallback` 跟着 `false`） |
| `prefill: false` + `fallback: true` | — | 配置阶段直接报错（自相矛盾） |

公式模式与快照模式**两边一致**：`fallback: false` 时 Excel 公式里也不回落默认值。
`fallback: false` 与 `allow_blank: true` 常配对使用。

### 5.5 取值约束的两道闸

| 闸 | 在哪 | 挡什么 |
| --- | --- | --- |
| Excel 数据有效性 | `init` 时写进工作簿 | `choices` → 下拉列表；`min` / `max` → 数值范围。**帮人填对** |
| `check_value_constraints` | `render` / `validate` / `check` 每次读表后 | **判据**。挡粘贴、脚本写入、别人发来的旧文件，以及 Excel 表达不了的正则 |

要点：

- **空值默认算不合格**。声明了约束 = "必须给一个合法取值"。这正好治了"新插一个空 Case 列
  悄悄落进某个规则集"（给归属变量 `kind` 加 `choices` 就够了）。
- 某类型才有的字段 → `allow_blank: true`。在这之前唯一的绕法是往 `choices` 里塞空串
  （老配置仍能跑，但 `render` / `validate` 会给 `!` 提示建议改写；下拉里也不再出现空选项）。
  `allow_blank` 只管"空值本身合不合法"，**必填仍该由 `asserts` 表达**。
- `choices` **按文本比较**：`choices: [1, 2]` 里填 `1.0` 也算命中。
- `min` / `max` 只能给 `int` / `float` / `auto`；配 `type: string` 会在配置阶段报错。
- `pattern` 写不进 Excel（数据有效性没有正则），**只由工具检查**。
- `default` 自己也要满足约束。
- **派生参数不能加约束**：值算出来的，请在表达式里约束（`derived: "max(x, 0)"`）。
- 下拉列表两个硬限制（超出直接报错）：**选项里不能有逗号**；所有选项拼起来 **≤ 255 字符**。

报错形如：

```text
ERROR 参数取值不满足变量声明的约束，共 2 处：
  Global Parameter 第 2 行 'draft'：取值 205.59 大于上限 50
  Local Parameter 第 F 列 'EXT-T15' 第 2 行 'kind'：取值 （空） 不在允许列表 EXT/INT 里
  → 改 Excel 里的取值，或放宽 YAML 里的 min / max / choices / pattern
```

---

## 6. 派生参数 `derived:`

参数引用参数（同 Case 的 local + global），**不用填值**，模板里照常 `{{ 名字 }}`。

```yaml
variables:
  global:
    - {name: rho, type: float, default: 1025}
    - {name: rho_g, derived: "rho * g", type: float, suffix: " N/m^3"}
  local:
    - {name: h_s, derived: "max(draft - z, 0)", type: float, suffix: " m"}
    - {name: p_s, derived: "rho_g / 1000 * h_s", type: float}   # 可以引用派生参数
```

| 主题 | 说明 |
| --- | --- |
| 能引用什么 | `global` 与**同一个 Case** 的 `local`。**不跨 Case** |
| global 引用 local | ❌ 报错（global 没有"当前 Case"的概念） |
| 拿到的是 | **纯值**（`x.value` 语义），所以 `rho * g` 能直接算 |
| 自己的前后缀 | 照常生效（`{{ rho_g }}` 带单位） |
| 链式 | 可以引用别的派生参数，按依赖顺序求值；**成环报错**并给出环上的名字 |
| 名字范围 | 只能引用 YAML 里定义过的名字（表里临时加的不能作为派生引用） |
| 成员表里 | ❌ 不能用 |
| 参数表里 | 淡绿色格，写的是公式（能翻译时），**手工填的东西会被忽略并告警** |

**能翻译成 Excel 公式的白名单**（翻译不了就降级成"写死 Python 算好的值"并告警，
此时改输入要重跑 `--write-excel`）：

| 写 | Excel |
| --- | --- |
| `min(a,b)` / `max(a,b)` | `MIN` / `MAX` |
| `abs(x)` / `\|abs` | `ABS` |
| `int(x)` / `\|int` | `TRUNC`（Excel 的 `INT` 向下取整，与 Python `int` 不同） |
| `float(x)` / `\|float` | 原值 |
| `len(x)` / `x \| len` / `x \| length` | `LEN`（量的是**纯值**） |
| `x \| string` | 原值 |
| `+ - * / ** %` | `+ - * / ^ MOD` |
| `~`（字符串拼接） | `&` —— **不要用 `+` 拼字符串**，Excel 的 `+` 不做文本拼接 |
| 比较 / `and` / `or` / `not`（只在条件里） | `= <> > < >= <=` |
| `a if cond else b` | `IF(cond,a,b)` |
| `x.value` / `x.text` / `x.prefix` / `x.suffix` | 对应列 |

**不翻译**（降级 + 告警）：`round`（Python 银行家舍入 vs Excel 四舍五入）、`ceil` / `floor`、
`//`、`upper` / `lower` / `strip` / `replace` / `format`、`sum` / `sorted` / `join`、
其它属性访问。报错会说明是**哪一条原因**并列出白名单。

---

## 7. `extends` —— 跨文件复用

```yaml
# project.yaml —— 工作簿的真源
extends:
  - rules/external.yaml      # 路径相对**本文件**
  - rules/internal.yaml
excel:
  output: "project.xlsx"
  sheets:
    outputs: ["Code EXT", "Code INT"]
```

被 extends 的文件就是普通单文件配置，**单独拿出来也必须能 validate 通过**。

| 对象 | 判据 |
| --- | --- |
| 同名变量 | **必须逐字一致**：`prefix`、`suffix`、`type`、`derived`、`min`/`max`/`choices`/`pattern`（它们决定生成的文本）—— 不一致**直接报错** |
| 同名变量 | **只告警**：`default`、`description`（不同规则集的示例工况本就不同），保留**先出现**的 |
| 同名模板 | 内容必须**完全一致**（一致则去重），否则报错 |
| `excel` | **只有根文件的生效**；被 extends 的文件里写了会告警并忽略 |
| `version` | 取根文件的 |
| `asserts` | 全部保留 |

合并顺序：按 `extends` 列表顺序先合并各文件，**最后合并根文件自己**的内容（同名时先出现的赢）。
`extends` 递归；循环引用报错并打出引用链。

---

## 8. `variables.group` —— 第三层作用域（成员表）

一个舱 / 设备被**多个工况**引用、参数只该写一遍时用它。

```yaml
variables:
  local:
    - name: tank_ref                    # 每个 Case 用它指向一个成员（**必须是 local**）
      choices: ["WBT6", "WBT7", "COT1"]
      default: "WBT6"
  group:
    sheet: "Tank Data"
    key: tank_ref
    members: ["WBT6", "WBT7", "COT1"]    # init 时先建哪几行；之后自己插行即可
    variables:                          # 成员自己的参数，一行一个成员，只写一遍
      - {name: l_tank, type: float, default: 42, unit: "m"}
      - {name: h_tank, type: float, default: 32}
```

**作用域优先级（低 → 高）**：**成员(group) → global → local → `case_name`**。

| 规则 | 说明 |
| --- | --- |
| `key` | **必须是 local 变量**（要"每个 Case 一列/一行"才能指向不同成员） |
| 成员来源 | 从**表里**发现；`members:` 只决定 `init` 先建哪几行 |
| `derived` | ❌ 成员表变量不能用 |
| `prefix` / `suffix` | 只来自 YAML（成员表没有这两列） |
| 取值约束 | ✅ 支持 `min`/`max`/`choices`/`pattern`，会写成数据有效性 |
| `asserts` / `case_filter` | 看得到成员值 |
| 名字冲突 | 与 global / local **不能重名**（配置阶段报错） |
| 公式模式 | ✅ 支持（嵌套一维 `INDEX/MATCH`） |

Case 的 `key` 指向不存在的成员时明确报错并列出可选成员。

**什么时候用**：一个舱 / 设备被多个工况引用 → ✅ 用；参数确实每个工况都不一样 → 放 `local`；
所有工况都一样的主尺度 → 放 `global`；需要**两层以上**引用（舱里再分部件）→ 表达不了。

---

## 9. `{% include %}` —— 模板片段复用

```jinja
{# templates/main.j2 #}
{% include "frag/constants.j2" %}
var L = {{ L }};
```

| 主题 | 说明 |
| --- | --- |
| 路径 | 相对**声明模板的那个文件**（与 `template_file` 同一套规则） |
| 嵌套 | ✅ 支持；循环 include 会被跳过 |
| 变量引用 | 片段里用到的变量同样算"被引用"，`validate` 会检查 |
| 引擎 | **只支持快照模式**；公式模式明确报错（片段让"一个 Case 占几行"不可预测） |

> 复用**变量与整份模板** → `extends`（§7）；复用**模板里的一段** → `{% include %}`（§9）。

---

## 10. `templates[]`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `name` | str | **必填** | 模板唯一名（也用于文件名默认值与日志） |
| `description` | str | `""` | 注释 |
| `output_sheet` | str | `Output` | 写回哪张表；**必须**已在 `excel.sheets.outputs` 声明 |
| `start_cell` | str | `B2` | 结果起始单元格，如 `B2` / `A1` / `H5`（`2B`、`B0` 非法） |
| `direction` | `horizontal` \| `vertical` | `horizontal` | **输出**布局，见 §11 |
| `write_case_headers` | bool | `true` | 是否写 Case 名表头（横向写在上一行，纵向写在左一列） |
| `filename` | str \| null | `null` | 导出文件名，支持 Jinja2：`{{ case_name }}` / `{{ template_name }}` / **这个 Case 的任意变量** |
| `extension` | str | `.txt` | 未配 `filename` 时的默认扩展名（自动补 `.`） |
| `code` | str | — | 内联模板源码（与 `template_file` 二选一） |
| `template_file` | str | — | 外部模板路径，**相对 YAML 所在目录** |
| `engine` | `snapshot` \| `excel` | **`excel`** | 输出引擎，见 `engine-preflight.md` |
| `case_filter` | str \| null | `null` | Jinja2 **表达式**（不要加 `{{ }}`），为假则本模板跳过该 Case |

`code` 与 `template_file` **必须提供其一**；都写时以 `template_file` 为准。

`case_filter` 示例：`kind == 'EXT'`、`kind.value == 'EXT'`、`draft.value > 20`。
**数值比较必须用 `.value`**（裸变量是组合值）。`--case` 是全局过滤，`case_filter` 是 per-template 过滤，
两者可叠加；被跳过的 Case 不占输出列 / 行。

### 导出文件名

- 优先级：`filename` → 否则 `<模板名>_<Case名><extension>`。
- 文件名里的 `<>:"/\|?*` 与控制字符会替换成 `_`（Windows 兼容）—— 这**意味着文件名里不能带目录**。
  `+`、`.`、`-`、空格、中文都安全，工况名可以直接当文件名用；要分目录请用不同的 `--outdir`。
- **多份结果求值成同一个文件名会被拦住**（写盘之前报错，并给出一条验证过的改名建议）。
  确实想只留最后一份，加 `--allow-overwrite-filename`。
- `--no-overwrite` 挡的是"目标文件已存在"，**挡不住本次运行内部互相覆盖**。

---

## 11. 输出布局

| 配置 | 管什么 | 取值 |
| --- | --- | --- |
| `excel.local_direction` | **输入**：Local 表里工况怎么排 | `horizontal`（一列一个工况）/ `vertical`（一行一个工况） |
| `template.direction` | **输出**：结果写到哪一行 / 列 | `horizontal` / `vertical` |

**互不影响**：`local_direction: vertical` + `direction: horizontal` 是最常用的组合
（参数按行填、结果按列排）。

**horizontal 输出**——一个 Case 一列，第 n 行结果来自渲染结果的第 n 行：

```
      A          B                     C
1                Case1                 Case2          <- Case 表头（start_cell 上一行）
2   （空闲）     // Case: Case1        // Case: Case2
3                UART_Init(...);       UART_Init(...);
```

**vertical 输出**——一个 Case 一行，模板里的换行横向展开（适合 Markdown / CSV / 汇总）：

```
      A        B       C       D
2     Case1    line1   line2   line3
3     Case2    line1   line2   line3
```

> 渲染结果里的**空行也各占一行**。写 `{% if %}` 时用 `{%- ... -%}` 控空白，
> 否则给"逐行写进 Excel 再整列复制"的用法添噪音。

### `excel.local_direction: vertical` 的输入表

| | A | B | C |
| --- | --- | --- | --- |
| 1 | `Case` | `kind` | `draft` |
| 2 | `LC1` | `EXT` | `20.5` |

- `A2` 起每行非空的 A 列就是一行工况，名字直接成为 `{{ case_name }}`。
- **行必须连续**，从第 2 行开始，**遇到第一个空 A 格即停**，中间不要留空行。
- **没有 Prefix / Suffix 列**（前后缀只来自 YAML）。
- 切换布局 = 重做工作表（工具读不回旧形状），要备份 → `init --force` → 重填 → 重跑。

---

## 12. 报错速查

| 报错 | 原因 |
| --- | --- |
| `YAML 解析失败 …（第 N 行，第 M 列）` | 缩进 / 引号 / 块标量写错；中文值建议加引号 |
| `YAML 键重复: 'x'（第 N 行）` | 同一映射里写了两遍（常见于两块 `variables:`） |
| `start_cell: 非法单元格引用` | 写成了 `2B` / `B0` |
| `output_sheet 'X' 未在 excel.sheets.outputs 中声明` | 忘了登记输出表 |
| `变量名 'a-b' 不是合法标识符` | 含 `-`、空格、中文；或用了保留名 |
| `模板 'x' 变量缺失: 'y' is undefined` | `StrictUndefined`：模板引用了上下文没有的变量 |
| `模板 'x' 的 case_filter 求值失败` | 数值比较没写 `.value` |
| `参数取值不满足变量声明的约束` | 越界 / 不在 `choices` / 空值（声明了约束） |
| `参数不满足 YAML 里的 asserts` | 组合条件不成立 |
| `无法写回 Excel … 文件被 Excel 占用？` | 工作簿正在 Excel 里开着（退出码 4） |

更全的对照表见 `cli-and-errors.md`。
