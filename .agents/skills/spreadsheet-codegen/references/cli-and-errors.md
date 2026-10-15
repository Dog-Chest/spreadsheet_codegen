# 命令、退出码与报错对照

六个命令：`init` → 人填写 → `render`，另有 `validate` / `check` / `doctor` 与 `examples`。
全局 `--version`。所有命令的 `-c/--config` 都是**必填**。

**路径规则（容易搞混，记住这一条）**：配置里的相对路径（`excel.output`、`template_file`、
片段）一律**相对配置文件所在目录**解析；命令行给的 `-o` / `-x` / `--outdir` 相对**当前工作目录**。
摘要里一律打印规范化后的**绝对路径**。

---

## 1. 各命令要点

### `init` —— 生成 Excel 表单

| 选项 | 说明 | 默认 |
| --- | --- | --- |
| `-o, --output PATH` | 输出工作簿（相对**当前工作目录**） | 配置里的 `excel.output` |
| `--cases VALUE` | 初始工况：数量 `3` **或**逗号分隔的名字 `EXT-T20.559,INT-T15` | `2` |
| `-f, --force` | 覆盖已存在的工作簿 | 否 |
| `-y, --yes` | 配合 `--force`：确认"填过参数也要重建" | 否 |
| `--template-sheet / --no-template-sheet` | 生成隐藏的 `Template` 表 | 生成 |
| `--howto / --no-howto` | 生成 `HOWTO` 说明表（第一张） | 生成 |
| `--comments / --no-comments` | 变量名加 Excel 批注（描述/单位/类型/约束/前后缀/派生式） | 生成 |
| `--scripts / --no-scripts` | 生成一键刷新脚本 `<工作簿名>_render.bat` / `.sh` | 生成 |
| `--prerender / --no-prerender` | 建完就把输出写进去（公式模式下因此开箱可用） | 预填 |

> **`--force` 是数据丢失点。** 工具会比参数指纹，发现"这本工作簿里已经不是 YAML 默认值"时会拒绝，
> 并告诉你要加 `--yes` 才能丢。刚生成、没人动过的工作簿不会被拦。
> 参数过不了取值约束或 `asserts` 时，`init` 会**跳过预填并说明原因**，骨架照常生成，不会失败。

### `render` —— 渲染并输出

| 选项 | 说明 | 默认 |
| --- | --- | --- |
| `-x, --excel PATH` | 已填写的工作簿 | 配置里的 `excel.output` |
| `-w, --write-excel` | 把结果写回 Excel 的 Output 表（刷新 HOWTO / 指纹） | **否** |
| `-d, --outdir PATH` | 把结果导出为代码文件 | 否 |
| `--case NAME` | 只渲染指定 Case（可重复） | 全部 |
| `--show / --no-show` | 终端打印渲染结果 | `--show` |
| `--overwrite / --no-overwrite` | 导出文件已存在时覆盖 | 覆盖 |
| `--allow-overwrite-filename` | 放行"多份结果写进同一个文件名" | 否 |

`--write-excel` 与 `--outdir` **可以一起给**。两者都不给时**只预览**（安全模式），
摘要里会写「写回 Excel │ 否（需要 --write-excel）」。

> **文件名冲突会被拦住**（0.11.0 起）：`filename: "vault.jsonl"` 会让 3 个 Case 互相覆盖，
> 静默只剩最后一份。工具在**写盘之前**报错，并给出一条**验证过**的改名建议；
> 同一个模板内部、跨模板写同一个 `--outdir` 都算冲突。确实想只留最后一份就加
> `--allow-overwrite-filename`。
> `--no-overwrite` 挡的是"目标文件已存在"，**挡不住本次运行内部互相覆盖**。

### `validate` —— 只校验，不产出

不带 `-x`：查 YAML 结构、模板 / `case_filter` 的 Jinja 语法、`{% include %}` 片段是否存在、
模板引用的变量是否定义、**定义了却没被引用的变量**、`output_sheet` 是否声明、变量重名、Case 一览。

带 `-x`：再查 Excel 结构、**取值约束**（`min`/`max`/`choices`/`pattern`）、根级 **`asserts`**
（跨变量校验，每个 Case 一起求值）、成员表取值。一次列出全部越界处。

### `check` —— 判定"表里的代码是否已过期"（CI 用这个）

| 选项 | 说明 | 默认 |
| --- | --- | --- |
| `-x, --excel PATH` | 要检查的工作簿 | 配置里的 `excel.output` |
| `--values / --no-values` | 公式模式：把 Output 表的公式在 Python 里算一遍再比对 | 开 |
| `--json` | 结果打成 JSON（stdout 上只有 JSON，方便 `jq` / CI） | 否 |

- 快照模式：重新渲染，与表内内容逐行比对（含 Case 表头）。
- 公式模式：① 比公式文本；② **把公式求值**再与 Python 渲染比对 —— 后者能抓到
  "列标指错 / 空单元格处理错"这类**公式本身**的问题，以及"插删过 Case 列"这种结构变化。
- 差异**按行列出**（每个 Case 最多 5 行，其余折成"还有 N 行不同"），公式模式还会指出**模板第几行**。

JSON 结构：`ok` / `config` / `excel` / `recorded{time,input_fingerprint,output_fingerprint}` /
`current{...}` / `drift` / `warnings` / `problems` / `problem_kinds`。
`problems` 是给人读的话术，`problem_kinds` 是**稳定枚举**（同下标一一对应）：

| `kind` | 含义 | 自动处置 |
| --- | --- | --- |
| `output_stale` | 输出表内容与当前 YAML / 参数不一致 | 可以自动重跑 `--write-excel` |
| `value_mismatch` | 公式文本一致，但"公式算出来的"与 Python 渲染不同（结构改过？） | **直接失败**，要人看 |
| `case_header` | 输出表 Case 表头与参数表对不上 | 要人看 |
| `missing_sheet` | 输出表不存在 | 多半要 `init` |
| `no_matching_case` | `case_filter` 把所有 Case 都跳过了，旧内容无法核对 | 要人看 |

### `doctor` —— 环境 / 配置 / 工作簿三层体检

新同事拿到仓库的**第一条命令**、发版前自检。工作簿坏掉时**只变成报告里的一行 ERROR，
不会甩 traceback**（跑 doctor 的时候工作簿往往正好就是坏的）。
多层同时出问题时取**数值最大**的那类（`4` 环境 > `2` 配置 > `1` 其他）。

### `examples` —— 内置示例（包数据）

```bash
spreadsheet-codegen examples                          # 列出
spreadsheet-codegen examples --copy ./examples        # 全部拷出
spreadsheet-codegen examples --copy . --only abs_fpi  # 只要一个
```

装了 pip 包就有，**不需要克隆仓库**。拷出来的每个示例都带一本**已填好样例参数**的工作簿。
`--force` 之外不会覆盖已有内容。

---

## 2. 退出码（CI 里怎么分流）

| 退出码 | 含义 | 谁会给 |
| --- | --- | --- |
| `0` | 成功 | 全部 |
| `1` | 通用失败（模板语法、变量缺失、工作簿结构不对） | 全部 |
| `2` | **配置 / 取值错误**：YAML 写错、取值越界、`asserts` 不满足、公式模式表达不了 | init/render/validate/check/doctor |
| `3` | **输出过期** | `check` |
| `4` | **环境问题**：工作簿打不开 / 写不进（被 Excel 占用等） | init/render/validate/check/doctor |

```bash
spreadsheet-codegen check -c project.yaml || case $? in
  3) echo "输出过期，自动重渲染"; spreadsheet-codegen render -c project.yaml -x book.xlsx --write-excel ;;
  2) echo "参数或配置不对，得人来改"; exit 1 ;;
  *) echo "其他失败"; exit 1 ;;
esac
```

> **文件不存在**（还没跑 `init`）走 `1`，**不是** `4` —— 那是"忘了生成"，不是"环境坏了"。

---

## 3. 错误类型（库调用方也照这个分）

全部继承自 `CodeGenError`；CLI 以 `ERROR 提示` 打印并按上表返回。

| 异常 | 触发场景 | 退出码 |
| --- | --- | --- |
| `ConfigError` | YAML 语法错、同一映射里键重复、字段非法、重名、`output_sheet` 未声明 | 2 |
| `InputError`（`ExcelError` 子类） | 表里填的取值不对：越界、`choices` 不匹配、`asserts` 不满足、成员名不存在 | 2 |
| `ExcelError` | 文件不存在、工作表缺失、表头不对、没有工况、变量名重复 | 1 |
| `WorkbookIOError`（`ExcelError` 子类） | 工作簿读不出来 / 写不进去：损坏、被 Excel 占用、没权限 | 4 |
| `RenderError` | 模板 / `case_filter` 语法错、变量缺失、导出文件名非法 | 1 |
| `FormulaError` | 模板写法公式模式表达不了（`{% for %}`、过滤器、跨行分支） | 2 |

---

## 4. 报错 → 修法 对照表

| 现象 / 报错 | 原因 | 处理 |
| --- | --- | --- |
| `YAML 解析失败 …（第 N 行，第 M 列）` | 缩进 / 引号 / 块标量写错 | 按行号查；中文值建议加引号 |
| `YAML 键重复: 'x'（第 N 行）` | 同一映射里写了两遍同名键（PyYAML 默认静默覆盖） | 按行号合并（常见于写了两块 `variables:`） |
| `配置校验失败 … start_cell: 非法单元格引用` | `start_cell` 写成 `2B` / `B0` | 改成 `B2` 形式 |
| `… output_sheet 'X' 未在 excel.sheets.outputs 中声明` | 模板输出表没声明 | 在 `excel.sheets.outputs` 里加 |
| `Excel 缺少工作表: 'Local Parameter'` | Excel 与 YAML 表名不一致，或用了旧模板 | 名字对齐，或 `init --force` 重生成 |
| `工作表 'Local Parameter' 从 E1 开始没有 Case 列` | Case 表头被删 / 挪走 | 在 E1 起恢复 `Case1`… |
| `模板 'x' 变量缺失: 'y' is undefined` | 模板引用了上下文没有的变量 | 在 YAML 加变量，或在表里加同名变量行 |
| `模板 'x' 语法错误：第 N 行 …` | Jinja 标签未闭合、`{% for %}` 缺目标 | 按行号改；成对检查 `if/endif`、`for/endfor` |
| `模板 'x' 的 case_filter 求值失败: …` | 做了非法比较（`draft > 20`）或变量取不到 | 数值比较写 `.value` |
| `公式模式不支持 …` | 模板里有 `{% for %}` / 过滤器 / 跨行 `{% if %}` | 改回 `engine: snapshot`，或把差异改成参数（优先） |
| `参数取值不满足变量声明的约束，共 N 处` | 表里的值越界 / 不在 `choices` / 空值（声明了约束） | 改表里的值，或放宽 YAML 约束 |
| `参数不满足 YAML 里的 asserts（跨变量校验）` | 组合条件不成立（吃水 > 型深…） | 改值或改 `asserts` |
| `ERROR 输出表已过期，共 N 处不一致` | 改了参数 / 结构但没跑 `render --write-excel` | 跑一次写回；`value_mismatch` 要人看 |
| `无法写回 Excel … 文件被 Excel 占用？` | 文件正在 Excel / WPS 里开着 | **让人关掉**再重试 |
| `变量名 'a-b' 不是合法标识符` | 名字含 `-`、空格、中文 | 改名或用下划线 |
| 输出里出现 `None` | 变量既没值也没 `default` | 给 `default: ""` |
| 数值变成 `115200.0` | 该变量是 `float` | 用 `type: int`（整数浮点默认已规范化） |
| 中文 Windows 下最后一行打不出来 / 退出码 1 | GBK 控制台 | 0.2.0 起已修：CLI 只用 ASCII 标记并把错误处理设为 `backslashreplace` |

---

## 5. 作为 Python 库使用

需要批量生成、代填参数、或写自定义校验时用这条路，不必拼命令行。

```python
from spreadsheet_codegen import (
    load_config,
    create_template,
    render_all,
    write_results,
    export_files,
    build_environment,
    input_fingerprint,
    output_fingerprint,
    read_metadata,
)

config = load_config("project.yaml")  # 读取并校验 YAML
create_template(config, "book.xlsx", cases=3, overwrite=True)
output = render_all(config, "book.xlsx")  # 读表 + 渲染
write_results("book.xlsx", config, output.results)  # 写回 Output 表 + 指纹
files = export_files(config, output.results, "generated/")

print(output.results["uart_init"][0].text)  # 某模板某 Case 的文本
print(output.skipped)  # case_filter 跳过了哪些 Case
print(input_fingerprint(output.global_values, output.cases))
```

> 这一条路对**成员表 / 派生参数 / 公式模式**都成立，但注意：`openpyxl` 不算公式，
> 所以代填参数时写进去的必须是**值**，不能指望工具帮你求值。
