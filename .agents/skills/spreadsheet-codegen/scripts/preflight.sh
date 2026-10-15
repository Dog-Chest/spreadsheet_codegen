#!/usr/bin/env bash
# 自检：spreadsheet-codegen 在不在、什么版本、整条链路通不通。
#
# 只读 + 只在 mktemp 出来的临时目录里写，**不会动你当前的项目**。
#
#   bash scripts/preflight.sh
#
# 退出码：0 通；1 没装 / 版本太老；其他非 0 = 工具本身的失败（含义见输出）。

set -u

# --------------------------------------------------------------------------- #
# 1. 找到 CLI（命令 → python3 -m → python -m）
# --------------------------------------------------------------------------- #
SCG=()
if command -v spreadsheet-codegen >/dev/null 2>&1; then
    SCG=(spreadsheet-codegen)
elif command -v python3 >/dev/null 2>&1 && python3 -m spreadsheet_codegen --version >/dev/null 2>&1; then
    SCG=(python3 -m spreadsheet_codegen)
elif command -v python >/dev/null 2>&1 && python -m spreadsheet_codegen --version >/dev/null 2>&1; then
    SCG=(python -m spreadsheet_codegen)
else
    echo "ERROR 没找到 spreadsheet-codegen。装一个：" >&2
    echo "        uv tool install spreadsheet-codegen      # 推荐" >&2
    echo "        pipx install spreadsheet-codegen         # 或" >&2
    echo "        pip install spreadsheet-codegen          # 或" >&2
    echo "      装完重跑本脚本。示例是包数据，不需要克隆仓库。" >&2
    exit 1
fi

echo "==> 命令：${SCG[*]}"

VERSION_RAW="$("${SCG[@]}" --version 2>&1 | head -n 1)"
echo "==> 版本：${VERSION_RAW}"

# 版本门禁：0.11.0 引入了分性质退出码与 prefill/fallback，本 skill 按它写。
VER="$(printf '%s' "$VERSION_RAW" | sed -n 's/.*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p')"
if [ -n "$VER" ]; then
    MAJOR="${VER%%.*}"
    REST="${VER#*.}"
    MINOR="${REST%%.*}"
    if [ "$MAJOR" -eq 0 ] && [ "$MINOR" -lt 11 ]; then
        echo "ERROR 版本过低（$VER）：本 skill 按 0.11.x 写，退出码与 prefill/fallback 都不同。" >&2
        echo "       升级：uv tool upgrade spreadsheet-codegen" >&2
        exit 1
    fi
fi

# --------------------------------------------------------------------------- #
# 2. 在临时目录里把内置示例跑一遍（不改动当前项目）
# --------------------------------------------------------------------------- #
TMP="$(mktemp -d "${TMPDIR:-/tmp}/scg-preflight.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

echo "==> 临时目录：${TMP}"
if ! "${SCG[@]}" examples --copy "$TMP" --only basic >/dev/null 2>&1; then
    echo "ERROR 拷不出内置示例 —— 这个安装可能不完整（示例应随包发布）。" >&2
    exit 1
fi

YAML="$TMP/basic/example_formula.yaml"
XLSX="$TMP/basic/template_formula.xlsx"
if [ ! -f "$YAML" ] || [ ! -f "$XLSX" ]; then
    echo "ERROR 示例文件不齐：缺少 $YAML 或 $XLSX" >&2
    exit 1
fi

echo "==> validate（配置 + 模板语法 + 工作簿结构）"
"${SCG[@]}" validate -c "$YAML" -x "$XLSX" >/dev/null 2>&1
VALIDATE_RC=$?
if [ "$VALIDATE_RC" -ne 0 ]; then
    echo "ERROR validate 失败（退出码 $VALIDATE_RC）。重跑去掉 >/dev/null 看详情。" >&2
    exit "$VALIDATE_RC"
fi

echo "==> check（表里的代码是否与当前参数一致；公式会在 Python 里算一遍）"
"${SCG[@]}" check -c "$YAML" -x "$XLSX" >/dev/null 2>&1
CHECK_RC=$?
if [ "$CHECK_RC" -ne 0 ]; then
    echo "ERROR check 失败（退出码 $CHECK_RC）。重跑去掉 >/dev/null 看详情。" >&2
    exit "$CHECK_RC"
fi

echo
echo "OK 链路通了：示例 validate + check 都是 0。可以开始干活了。"
echo "   下一步：读 SKILL.md 的「流程 A」，或直接"
echo "   bash scripts/new-library.sh <你的目录>"
