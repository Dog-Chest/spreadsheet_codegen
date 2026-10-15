---
name: spreadsheet-codegen
description: "把一组只有参数不同、结构几乎一样的代码或配置，做成「在 Excel 里填参数 → 代码自动跟着变」的生成器（Excel-driven / spreadsheet-driven code generation）。当用户要把重复代码模板化、想让工程师在表格里填参数而不用碰命令行、要把工况表 / 参数表 / 设备表变成 C / JS / Python / NASTRAN / CSV / JSON / 配置文件、要新建或维护 spreadsheet-codegen 的 YAML 模板库（init、render、validate、check、doctor；公式模式与快照模式；prefix/suffix；case_filter；extends；成员表），或要排查「check 说输出过期」「模板语法报错」「公式模式不支持 Jinja 循环或过滤器」「变量未定义」时使用。"
---

# spreadsheet-codegen：把参数表变成代码生成器

你要替用户**建一套基于 Excel 的代码生成器**，再把它交给人在 Excel 里日常使用。先接受这个分工，
它决定了你什么时候算"做完了"：

| 谁 | 干什么 |
| --- | --- |
| **你** | 写 YAML（变量定义 + Jinja2 模板）、`init` 出工作簿、`validate` / `check` 验证、按需导出代码文件 |
| **人** | 在 Excel 的 Global / Local / 成员表里填参数、评审、改数 |
| **Excel / WPS** | 公式模式下**自己**重算代码 —— 改完参数不需要任何人再跑命令 |

所以 **YAML 是你交付的核心，工作簿是给人的界面**。不要假装自己在"填 Excel"：需要样例值就给
`default`，或用 `--cases` 预先命名工况，剩下的交给人。除非用户明确要求你代填，否则把工作簿填满
不是你的活，那是评审环节。

## 0. 先确认工具在不在

```bash
bash scripts/preflight.sh
```

它检查 `spreadsheet-codegen` 是否可用、打印版本，再把内置示例拷到临时目录跑一遍
`validate` + `check`，证明整条链路是通的。**没装**就 `uv tool install spreadsheet-codegen`
（或 `pipx install spreadsheet-codegen`）。**不要**为了用这个 skill 去克隆仓库 —— 示例是
**包数据**，装了包就有（`spreadsheet-codegen examples --copy`）。

> 本文按 **0.11.x** 写。0.11.0 才引入分性质退出码（0/1/2/3/4）与 `prefill` / `fallback`；
> 更早版本行为不同。`preflight.sh` 会报出实际版本。

## 1. 五句话心智模型

1. **YAML 是唯一真源**：进 Git、可 diff、可评审、可攒成模板库。Excel 只是给人的表单。
2. **流程是**：`init` 造表 → 人填 → `render --write-excel` 把结果写回 → `check` 判定是否过期。
3. **三层作用域**：成员表(group) < global < local < `case_name`，同名时后者覆盖前者。
4. **上下文里没有的变量直接报错**（`StrictUndefined`），不会静默变空串。
5. **默认引擎是 `engine: excel`**：Output 表里是**活的 Excel 公式**，改参数打开 Excel 就重算，
   工作簿脱离命令行也独立可用。这是这个工具最大的卖点，不要随手把它降级成 `snapshot`。

## 2. 写模板之前，先定引擎 ← 最容易翻车的一步

引擎决定**模板里能写什么**，所以必须在写模板**之前**定。判据不是"这个模板复不复杂"，
而是**用没用下面这些 Jinja 语法**：

| 模板里有 | `engine: excel`（默认） |
| --- | --- |
| 纯字面文本 + `{{ x }}` / `{{ x.value }}` / `{{ x.text }}` / `{{ x.prefix }}` / `{{ x.suffix }}` / `{{ case_name }}` / `{{ template_name }}` | ✅ |
| **同一行内**闭合的 `{% if %}` / `{% elif %}` / `{% else %}`（编译成 Excel `IF()`） | ✅ |
| `{# 注释 #}`（整段丢掉） | ✅ |
| `{% for %}`、`{% set %}`、`{% include %}` | ❌ 改用 `engine: snapshot` |
| **任何过滤器**：`{{ x \| upper }}`、`{{ x.value \| pvs("P","S") }}` | ❌ 改用 `snapshot` |
| **表达式 / 运算**：`{{ baud + 1 }}` | ❌ 改用 `snapshot` |
| **跨行**的 `{% if %}` | ❌ 改用 `snapshot` |
| 引用了 YAML 里没定义的变量 | ❌ 两种引擎都不行 |

### ⚠ 头号误判：生成目标语言自己的 `if / else` 不是 Jinja 控制流

生成目标里出现 `if (...) { } else { }`、`for`、`{ }` 都只是**字面文本**，公式模式照收不误。
真正拦住公式模式的是 **Jinja 的** `{% %}` / `{{ | 过滤器 }}`。见过太多模板因为"目标代码里有
if/else"被错误地降级成 `snapshot`，白白丢掉了"改参数免重跑"。**先试着按公式模式写**。

### 条件里的硬规矩

`{% if %}` 的条件里**变量必须带属性**（`.value` / `.text` / `.prefix` / `.suffix`），
只有 `case_name` / `template_name` 可以裸写：

```jinja
y = {% if flag.value == 1 %}{{ L }}{% else %}- {{ L }}{% endif %};   ✅
y = {% if flag == 1 %}{{ L }}{% else %}- {{ L }}{% endif %};         ❌ 报错：请写 flag.value
```

### 公式模式的成本

- 一个 `{{ x }}` 大约展开 **300–500 字符**（`INDEX` + `MATCH` + `ISBLANK` + 回落 + 前后缀）。
  一行 8 个以上占位符就该考虑拆行；单格硬上限 **8192 字符**，超了直接报错。
- 公式模式下**值只活在 Excel 里**：`--outdir` 导出的文件仍由 Python 渲染（因为模板是纯替换，
  内容等价），但"改了参数自动同步文件"做不到，要再跑一次。
- **改模板要重跑** `render --write-excel`；**改参数不用**；**增删/移动 Case 列要重跑**
  （公式里的相对列会指错），插删变量行不用（`INDEX/MATCH` 按变量名定位）。`check` 能发现这件事。

细节与完整支持矩阵见 [`references/engine-preflight.md`](references/engine-preflight.md)。

## 3. 流程 A：从零建一套模板库

1. **先问清楚三件事**（缺了就没法动手）：要生成什么文件、**哪些值每个工况不同**（→ local）、
   **哪些全项目共用**（→ global）、**有没有被多个工况复用的实体**（舱 / 设备 / 器件 → 成员表）。
2. **抄骨架**：`bash scripts/new-library.sh <目录>` 生成 `project.yaml` + `rules/` + `templates/`，
   或者从 `assets/minimal-formula.yaml` 起步。
3. **写变量**：名字必须是 `[A-Za-z_][A-Za-z0-9_]*`，不能用保留名 `case_name` / `template_name`。
   **单位放 `suffix`**（`suffix: " m"` → `340 m`）—— 注意前导空格是有意义的，不会被吃掉。
4. **定引擎**（见上一节），再写模板。外部模板放 `templates/xxx.j2`，用 `template_file` 引用，
   **路径相对声明它的那个 YAML**。
5. **加约束**：能声明取值范围的都声明 —— `min` / `max` / `choices`（Excel 下拉）/ `pattern`。
   跨变量规则用根级 `asserts`（如 `draft.value <= d_tank.value`）。这是挡"手滑把 20.559 打成
   205.59 却照样出代码"的唯一一道闸。
6. **生成工作簿**：`spreadsheet-codegen init -c project.yaml --cases A,B,C`。
   默认 `--prerender`，建完就是可用的。
7. **验证**：`validate -c ... -x ...` → `render -c ... -x ... --write-excel --outdir generated/`
   → `check -c ... -x ...`。
8. **交付话术**：告诉用户在**哪张表的哪些列**填参数、改完**不需要跑命令**（公式模式）、
   什么时候需要重跑（改结构 / 改模板）。

## 4. 流程 B：往已有的库里加东西

| 要加什么 | 怎么做 | 别忘了 |
| --- | --- | --- |
| 一个变量 | 加到 `variables.global` / `variables.local` | 名字合法、给 `description` 与 `default`（决定 `init` 预填什么）、单位放 `suffix` |
| 一个模板 | 加 `templates` 条目 | `output_sheet` **必须**已在 `excel.sheets.outputs` 里声明 |
| 一套规则集 | 新 YAML + 根文件 `extends: [rules/x.yaml]` | 各规则集单独拿出来也要 `validate` 得通 |
| 一个可复用片段 | 新建 `.j2`，用 `{% include "frag/x.j2" %}` | **只支持快照模式**，公式模式明确报错 |
| 第三层作用域 | `variables.group`（成员表） | `key` 必须是 local 变量；成员表变量不能 `derived` |
| 输入改成"一行一个工况" | `excel.local_direction: vertical` | **改布局要重建工作簿**，旧数据读不回来 |

一个工作簿放多套规则、共用一张 Global 表时，用 **`case_filter`**（per-template 过滤）而不是复制变量：

```yaml
templates:
  - name: ext_code
    output_sheet: "Code EXT"
    case_filter: "kind.value == 'EXT'"     # 推荐写 .value，配了前后缀也不受影响
```

`case_filter` 里数值比较**必须**用 `.value`（裸变量是组合值）。

## 5. 流程 C：诊断（先看退出码）

```bash
spreadsheet-codegen doctor -c project.yaml     # 环境 / 配置 / 工作簿三层体检，新同事第一条命令
```

| 退出码 | 含义 | 谁给的 | 怎么办 |
| --- | --- | --- | --- |
| `0` | 成功 | 全部 | — |
| `1` | 通用失败（模板语法、变量缺失、表结构不对） | 全部 | 读 ERROR 里的**行号 / 表名 / 列名** |
| `2` | **配置或取值错**（YAML 写错、取值越界、`asserts` 不满足、公式模式表达不了） | init/render/validate/check/doctor | 改 YAML 或改表里的值，**要人来决定** |
| `3` | **输出过期**（表里的代码与当前参数不一致） | `check` | 跑 `render --write-excel` 刷新 |
| `4` | **环境问题**（工作簿打不开 / 写不进，多半是 Excel 正开着它） | init/render/validate/check/doctor | 让人关掉 Excel 再重试 |

CI 里就该按这个分流 —— 3 可以自动重渲染，2 必须交给人。`check --json` 给出机器可读的
`problems` 与**稳定枚举** `problem_kinds`（`output_stale` / `value_mismatch` / `case_header` /
`missing_sheet` / `no_matching_case`）。

排错清单见 [`references/cli-and-errors.md`](references/cli-and-errors.md)，实测踩过的坑见
[`references/pitfalls.md`](references/pitfalls.md)。

## 6. 交付标准

一份工作交付前，下面三件事都要成立：

1. `validate -c <yaml> -x <xlsx>` 干净（没有 `!` 提示更好）；
2. `check -c <yaml> -x <xlsx>` **退出码 0**；
3. 摘要里明确写出「写回 Excel │ 是」和导出目录的**绝对路径** —— 否则你只是预览了，什么都没落盘。

> `render` 不带 `--write-excel` 和 `--outdir` 时**只预览**。0.11.0 起它会明确标注，但你自己
> 别把"跑成功了"当成"写进去了"。

## 7. 用它的边界（别硬凹）

- **只有三层作用域**（船 → 工况 → 舱/设备）。再往下（舱里再分部件）表达不了。
- **不做语义检查**：它不认识 C / GeniE / NASTRAN 的语法，`Math.sin(90)` 照过。业务正确性得靠下游校验器。
- **不解决"引用别的表"**：判据很简单 —— 需要"引用别的表/别的层"就表达不了；
  只是"同一套模板 × 多个工况取值"它就能做。
- **单个变量跨 Case 联动**做不到，要在 Excel 里用公式。
- 生成的是**工程计算代码**时，交付话术里要提醒用户独立复核（这个仓库自己的免责声明就是这个口径）。

## 8. 参考资料

本 skill **自包含**：把这个文件夹整个拷走，不依赖任何外部文档、也不依赖仓库布局。

| 文件 | 什么时候读 |
| --- | --- |
| [`references/yaml-reference.md`](references/yaml-reference.md) | **字段级权威定义**：根节点 / `excel` / 变量 / 模板 / `extends` / 成员表 / `asserts` 的每个字段、默认值与报错 |
| [`references/engine-preflight.md`](references/engine-preflight.md) | 定引擎、公式模式报错、公式太长、值不一致 |
| [`references/excel-layout.md`](references/excel-layout.md) | 要告诉人"在哪张表哪一列填"、改布局、成员表 |
| [`references/cli-and-errors.md`](references/cli-and-errors.md) | 六个命令的选项、退出码分流、报错对照表、Python 库用法 |
| [`references/pitfalls.md`](references/pitfalls.md) | 症状 → 成因 → 修法；真实项目里翻过的车 |

要**能真正打开**的完整示例（不只是片段），用工具自带的包内示例 —— 不联网、不克隆任何仓库：

```bash
spreadsheet-codegen examples                 # 看有哪三个、各自演示什么
spreadsheet-codegen examples --copy ./demo   # 拷出来，每本工作簿都已填好样例参数
```

`assets/` 里另有三个最小起点：`minimal-formula.yaml`（公式模式）、`minimal-snapshot.yaml`
（快照模式）、`library-skeleton/`（`extends` + `case_filter` + `asserts` 的骨架，
配 `scripts/new-library.sh` 一键铺开）。
