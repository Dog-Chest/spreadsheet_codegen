"""``.agents/skills/spreadsheet-codegen/`` —— 随仓库发布的 agent skill 包。

skill 是**给 agent 看的操作手册**，本身不参与构建、不被 import，所以它最容易烂掉的地方
不是代码，而是三件"没人跑就发现不了"的事：

1. **frontmatter**：``name`` 必须 kebab-case 且与目录同名；``description`` 是模型能看到的
   **唯一**触发依据（catalog 那一行只渲染 name + description，上限 500 字符）。
   frontmatter 一旦解析失败，provider 会**静默跳过整个 skill** —— 不报错，它只是不再存在。
   这个坑真的踩过：``description`` 里写了 ``engine: excel``，冒号加空格让 YAML 把它当成了
   mapping，整个 skill 就消失了。所以这里用 PyYAML **真解析一遍**。
2. **相对路径**：SKILL.md 用 ``../../../docs/template_guide.md`` 指回仓库文档。文档改名或挪目录
   之后，agent 会照着一条死链去读，然后开始猜 —— 比 skill 不存在更糟。这里逐条解析。
3. **assets**：``assets/`` 里的 YAML 是"拷走就能用"的起点，必须真的能过 ``validate``，
   而且骨架能一路跑到 ``check`` 退出码 0。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from spreadsheet_codegen.cli import app

runner = CliRunner()

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".agents" / "skills" / "spreadsheet-codegen"

#: catalog 里每条 description 的渲染上限（dsh-tool-skill 的 catalogDescriptionMaxLength）。
DESCRIPTION_MAX_LENGTH = 500

#: skill 名必须匹配 provider 的 kebab-case 校验（`^[a-z0-9]+(?:-[a-z0-9]+)*$`）。
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: assets/ 下每个"拷走就能用"的配置，都必须能单独 validate 通过。
ASSET_CONFIGS = (
    "assets/minimal-formula.yaml",
    "assets/minimal-snapshot.yaml",
    "assets/library-skeleton/project.yaml",
    "assets/library-skeleton/rules/primary.yaml",
)


def _output(result) -> str:
    return (result.output or "") + (getattr(result, "stderr", "") or "")


def _skill_markdown() -> list[Path]:
    return sorted(SKILL_DIR.rglob("*.md"))


# --------------------------------------------------------------------------- #
# 1. frontmatter：解析不了 = 整个 skill 静默消失
# --------------------------------------------------------------------------- #
def test_bundle_exists() -> None:
    assert SKILL_DIR.is_dir(), f"skill 目录不在：{SKILL_DIR}"
    assert (SKILL_DIR / "SKILL.md").is_file(), "skill 根目录必须有 SKILL.md"


def test_skill_md_has_parseable_frontmatter() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md 必须以 YAML frontmatter 开头"

    parts = text.split("---", 2)
    assert len(parts) >= 3, "frontmatter 没有闭合的 ---"
    data = yaml.safe_load(parts[1])
    assert isinstance(data, dict), "frontmatter 不是一个 mapping"
    assert set(data) >= {"name", "description"}, "frontmatter 必须至少有 name 与 description"


def test_skill_name_is_kebab_case_and_matches_directory() -> None:
    data = yaml.safe_load((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1])
    name = data["name"]
    assert isinstance(name, str) and SKILL_NAME_RE.match(name), f"不是合法 kebab-case：{name!r}"
    assert name == SKILL_DIR.name, "frontmatter 的 name 与目录名必须一致，否则人找不着它"


def test_description_fits_the_catalog_budget() -> None:
    """description 是模型唯一的触发依据，被截断在 500 字符 —— 不能超，也不能是空的。"""
    data = yaml.safe_load((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1])
    description = data["description"]
    assert isinstance(description, str) and description.strip(), "description 不能为空"
    assert len(description) <= DESCRIPTION_MAX_LENGTH, (
        f"description {len(description)} 字符，超过 catalog 上限 {DESCRIPTION_MAX_LENGTH}"
    )


def test_no_nested_skill_files() -> None:
    """provider 的发现只有一层：``<root>/<name>/SKILL.md``。

    包里再放一个 SKILL.md（例如 references/ 下），它既不会被发现，还会让人以为它是入口。
    """
    nested = [path.relative_to(SKILL_DIR).as_posix() for path in SKILL_DIR.rglob("SKILL.md")]
    assert nested == ["SKILL.md"], f"包内只应有根目录一个 SKILL.md，实际：{nested}"


# --------------------------------------------------------------------------- #
# 2. 相对路径：死链比"skill 不存在"更糟 —— agent 会照着它去读，然后开始猜
# --------------------------------------------------------------------------- #
def test_repo_relative_references_resolve() -> None:
    """SKILL.md 里 ``../../../docs/xxx.md`` 这类指回仓库的路径必须存在。

    注意它是**相对声明它的那个文件**解析的：所以 ``../../../`` 只在 SKILL.md（skill 根）里成立，
    写进 ``references/`` 就会指到别处 —— 这条测试正是拦这个。
    """
    pattern = re.compile(r"(\.\./[\w./\-]*)")
    missing: list[str] = []
    for path in _skill_markdown():
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            target = (path.parent / match.group(1).rstrip("/")).resolve()
            if not target.exists():
                missing.append(f"{path.relative_to(SKILL_DIR)} → {match.group(1)}")
    assert not missing, f"指回仓库的相对路径解析不到（文档改名/挪目录了？）：{missing}"


def test_markdown_links_resolve() -> None:
    """包内 markdown 链接（`](...)`）指向的文件必须存在，且不能指到包外。"""
    pattern = re.compile(r"\]\(([^)]+)\)")
    broken: list[str] = []
    for path in _skill_markdown():
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(SKILL_DIR)} → {target}")
    assert not broken, f"包内链接指向了不存在的文件：{broken}"


# --------------------------------------------------------------------------- #
# 3. assets：拷走就能用，不能是"半份"的
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("relative", ASSET_CONFIGS)
def test_asset_config_validates(relative: str) -> None:
    """每个 asset 都要能单独 validate 通过（模板语法、template_file 存在、变量引用都对）。"""
    path = SKILL_DIR / relative
    assert path.is_file(), f"缺 asset：{relative}"
    result = runner.invoke(app, ["validate", "-c", str(path)])
    assert result.exit_code == 0, f"{relative} validate 失败：{_output(result)}"


def test_asset_library_skeleton_runs_end_to_end(tmp_path: Path) -> None:
    """骨架要能一路跑到 ``check`` 退出码 0 —— 否则 agent 的第一步就失败。"""
    import shutil

    dest = tmp_path / "library"
    shutil.copytree(SKILL_DIR / "assets" / "library-skeleton", dest)
    config = str(dest / "project.yaml")

    result = runner.invoke(app, ["init", "-c", config, "--cases", "EXT-1,EXT-2", "--no-scripts"])
    assert result.exit_code == 0, f"init 失败：{_output(result)}"

    result = runner.invoke(app, ["render", "-c", config, "--write-excel", "--no-show"])
    assert result.exit_code == 0, f"render 失败：{_output(result)}"

    result = runner.invoke(app, ["check", "-c", config])
    assert result.exit_code == 0, f"check 不是 0：{_output(result)}"


# --------------------------------------------------------------------------- #
# 4. scripts：语法与可执行位
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["preflight.sh", "new-library.sh"])
def test_script_is_executable_and_parses(name: str) -> None:
    path = SKILL_DIR / "scripts" / name
    assert path.is_file(), f"缺脚本：scripts/{name}"
    assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash"), f"{name} 缺 shebang"

    checked = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
    assert checked.returncode == 0, f"{name} 语法错误：{checked.stderr}"


def test_new_library_script_scaffolds_the_bundle(tmp_path: Path) -> None:
    """``new-library.sh`` 生成的东西必须与 assets 里的骨架一致（它就是拷贝那个目录）。"""
    dest = tmp_path / "scaffold"
    result = subprocess.run(
        ["bash", str(SKILL_DIR / "scripts" / "new-library.sh"), str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"new-library.sh 失败：{result.stderr}"

    for relative in ("project.yaml", "rules/primary.yaml", "templates/primary.js.j2"):
        assert (dest / relative).is_file(), f"骨架少了 {relative}"

    # 生成出来的必须是能 validate 的配置，而不只是几个文件摆在那儿。
    checked = runner.invoke(app, ["validate", "-c", str(dest / "project.yaml")])
    assert checked.exit_code == 0, f"生成出来的骨架 validate 失败：{_output(checked)}"
