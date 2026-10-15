#!/usr/bin/env bash
# 从一个可用骨架起一套模板库：project.yaml + rules/ + templates/。
#
#   bash scripts/new-library.sh <目标目录> [--force] [--init]
#
#   --force  目标目录已存在且非空时也照写（默认拒绝，避免覆盖你改过的文件）
#   --init   生成后顺手跑一次 spreadsheet-codegen init
#
# 骨架内容见 ../assets/library-skeleton/ —— 它本身就是一个 validate 得通的配置，
# 所以这里只是拷贝 + 报出下一步，不做任何"智能改写"。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKELETON="${SCRIPT_DIR}/../assets/library-skeleton"

TARGET=""
FORCE=0
RUN_INIT=0

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --init)  RUN_INIT=1 ;;
        -h|--help)
            sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        -*)
            echo "ERROR 未知选项：$arg" >&2; exit 2 ;;
        *)
            if [ -n "$TARGET" ]; then echo "ERROR 只能给一个目标目录" >&2; exit 2; fi
            TARGET="$arg" ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "用法：bash scripts/new-library.sh <目标目录> [--force] [--init]" >&2
    exit 2
fi

if [ ! -d "$SKELETON" ]; then
    echo "ERROR 找不到骨架目录：$SKELETON" >&2
    echo "      （本脚本要跟 assets/ 一起用，单独拷走会失效）" >&2
    exit 1
fi

if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ] && [ "$FORCE" -ne 1 ]; then
    echo "ERROR 目标目录已存在且非空：$TARGET" >&2
    echo "      确认要覆盖就加 --force（不会备份）。" >&2
    exit 1
fi

mkdir -p "$TARGET"
cp -R "$SKELETON/." "$TARGET/"

echo "OK 已生成模板库骨架：$TARGET"
echo
echo "    $TARGET/project.yaml                  根配置（excel 段 + extends）"
echo "    $TARGET/rules/primary.yaml            一套规则集（可单独 validate）"
echo "    $TARGET/templates/primary.js.j2       模板（公式模式安全）"
echo
echo "下一步："
echo "    1) 改 rules/primary.yaml 里的变量与 templates/primary.js.j2 的内容"
echo "    2) cd $TARGET && spreadsheet-codegen validate -c project.yaml"
echo "    3) spreadsheet-codegen init -c project.yaml --cases EXT-1,EXT-2"
echo "    4) 在 Excel 里填参数（Global 的 B 列；Local 的 E 列起）"
echo "    5) spreadsheet-codegen check -c project.yaml      # 退出码 0 才算完"

if [ "$RUN_INIT" -eq 1 ]; then
    echo
    echo "==> 跑 init"
    if command -v spreadsheet-codegen >/dev/null 2>&1; then
        ( cd "$TARGET" && spreadsheet-codegen init -c project.yaml )
    elif command -v python3 >/dev/null 2>&1 && python3 -m spreadsheet_codegen --version >/dev/null 2>&1; then
        ( cd "$TARGET" && python3 -m spreadsheet_codegen init -c project.yaml )
    else
        echo "ERROR 没找到 spreadsheet-codegen；先 uv tool install spreadsheet-codegen" >&2
        exit 1
    fi
fi
