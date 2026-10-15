"""``.agents/skills/spreadsheet-codegen/`` —— 随仓库发布的 agent skill 包。

skill 是**给 agent 看的操作手册**，本身不参与构建、不被 import，所以它最容易烂掉的地方
不是代码，而是三件"没人跑就发现不了"的事：

1. **frontmatter**：``name`` 必须 kebab-case 且与目录同名；``description`` 是模型能看到的
   **唯一**触发依据（catalog 那一行只渲染 name + description，上限 500 字符）。
   frontmatter 一旦解析失败，provider 会**静默跳过整个 skill** —— 不报错，它只是不再存在。
   这个坑真的踩过：``description`` 里写了 ``engine: excel``，冒号加空格让 YAML 把它当成了
   mapping，整个 skill 就消失了。所以这里用 PyYAML **真解析一遍**。
2. **自包含**：agent skill 的用法就是"把这个文件夹拷到某个被扫描的根下"，所以包内**不许**
   引用包外的任何路径。SKILL.md 一度用 ``../../../docs/template_guide.md`` 指回仓库 ——
   拷到 ``~/.dsh/skills/`` 或别的项目里，那些链接就全死了，而 agent 会照着死链去读、
   然后开始猜，比 skill 不存在更糟。这里既查链接、也**真拷出去跑一遍**。
3. **assets**：``assets/`` 里的 YAML 是"拷走就能用"的起点，必须真的能过 ``validate``，
   而且骨架能一路跑到 ``check`` 退出码 0。
"""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from spreadsheet_codegen.cli import app

runner = CliRunner()

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".agents" / "skills" / "spreadsheet-codegen"

#: ``.agents/`` 是**仓库侧**资产（给 agent 看的操作手册），不是包数据 —— ``MANIFEST.in``
#: 不收它，就像 ``abs_fpi/`` 被 prune 掉一样。而 ``tests/`` 是收进 sdist 的，CI 会把 sdist
#: 解包后整套跑一遍 pytest：那时这个文件在、目录却不在。所以整模块 skip，而不是失败。
#: （同一条规矩见 ``tests/test_abs_fpi_group.py`` 里的 ``_require``。）
if not SKILL_DIR.is_dir():  # pragma: no cover - 只有 sdist / 裁剪过的安装会走到
    pytest.skip("`.agents/skills/` 不在（sdist 里不带 skill 包）", allow_module_level=True)

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
# 2. 自包含：拷到别处还能用，是 skill 的全部意义
#
# 死链比"skill 不存在"更糟 —— agent 会照着它去读，然后开始猜。
# --------------------------------------------------------------------------- #
def _escapes_bundle(path: Path, target: str) -> bool:
    """``target``（相对 ``path`` 所在目录）解析后是否跑到 skill 包外。"""
    resolved = (path.parent / target.rstrip("/")).resolve()
    root = SKILL_DIR.resolve()
    return resolved != root and root not in resolved.parents


def test_no_reference_escapes_the_bundle() -> None:
    """包内正文不许出现指向包外的相对路径（裸路径与 markdown 链接都算）。"""
    offenders: list[str] = []
    for path in _skill_markdown():
        text = path.read_text(encoding="utf-8")
        targets = [match.group(1) for match in re.finditer(r"(\.\./[\w./\-]*)", text)]
        targets += [
            match.group(1).strip()
            for match in re.finditer(r"\]\(([^)]+)\)", text)
            if not match.group(1).strip().startswith(("http://", "https://", "mailto:", "#"))
        ]
        for target in targets:
            if _escapes_bundle(path, target):
                offenders.append(f"{path.relative_to(SKILL_DIR)} → {target}")
    assert not offenders, (
        "skill 包里出现了指向包外的路径 —— 这个文件夹被单独拷走（~/.dsh/skills/、别的项目）"
        f"之后它们会全部失效：{offenders}"
    )


def test_markdown_links_resolve() -> None:
    """包内 markdown 链接（`](...)`）指向的文件必须存在。"""
    broken: list[str] = []
    for path in _skill_markdown():
        for match in re.finditer(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (path.parent / target).resolve().exists():
                broken.append(f"{path.relative_to(SKILL_DIR)} → {target}")
    assert not broken, f"包内链接指向了不存在的文件：{broken}"


@pytest.fixture(scope="module")
def copied_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """把整个 skill 文件夹拷到别处 —— 就是用户"单独把它拿走"时发生的事。"""
    dest = tmp_path_factory.mktemp("skill-copy") / "spreadsheet-codegen"
    shutil.copytree(SKILL_DIR, dest)
    return dest


def test_assets_still_validate_after_the_bundle_is_copied_out(copied_bundle: Path) -> None:
    """拷到包外之后，四个 asset 仍然 validate 得通（路径没写死成仓库布局）。"""
    for relative in ASSET_CONFIGS:
        path = copied_bundle / relative
        assert path.is_file(), f"拷出来后缺 asset：{relative}"
        result = runner.invoke(app, ["validate", "-c", str(path)])
        assert result.exit_code == 0, f"拷出来后 {relative} validate 失败：{_output(result)}"


def test_new_library_script_works_from_the_copied_bundle(copied_bundle: Path, tmp_path: Path) -> None:
    """``new-library.sh`` 靠 ``脚本目录/../assets`` 找骨架 —— 拷走后这条相对路径必须还对。"""
    if sys.platform == "win32":  # pragma: no cover - 与下面 posix_only 同一条规矩
        pytest.skip("执行 .sh 需要 POSIX shell")

    dest = tmp_path / "scaffold"
    result = subprocess.run(
        ["bash", str(copied_bundle / "scripts" / "new-library.sh"), str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"从拷贝出来的包里跑 new-library.sh 失败：{result.stderr}"
    checked = runner.invoke(app, ["validate", "-c", str(dest / "project.yaml")])
    assert checked.exit_code == 0, f"生成出来的骨架 validate 失败：{_output(checked)}"


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
# 4. scripts：shebang、语法、可执行位
#
# 真要跑 bash 的用例在 Windows 上一律 skip —— 与 tests/test_run_scripts.py 同一条规矩
# （Windows 上 PATH 是 Unix 格式，也没有可执行位）。
# --------------------------------------------------------------------------- #
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="执行 .sh 需要 POSIX shell")

SCRIPT_NAMES = ("preflight.sh", "new-library.sh")


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_script_has_shebang(name: str) -> None:
    path = SKILL_DIR / "scripts" / name
    assert path.is_file(), f"缺脚本：scripts/{name}"
    assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash"), f"{name} 缺 shebang"


@posix_only
@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_script_parses(name: str) -> None:
    path = SKILL_DIR / "scripts" / name
    checked = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
    assert checked.returncode == 0, f"{name} 语法错误：{checked.stderr}"


@posix_only
def test_scripts_have_the_executable_bit() -> None:
    """git 里存的是 100755。

    这个位**不会**自己产生：本仓库的 NTFS 挂载上 ``core.filemode=false``，直接
    ``git add`` 会把新脚本记成 100644（clone 下来不能 ``./`` 跑）。所以新增脚本时要
    ``git add --chmod=+x``，这条测试是那个动作的回归。
    """
    for name in SCRIPT_NAMES:
        mode = (SKILL_DIR / "scripts" / name).stat().st_mode
        assert mode & stat.S_IXUSR, f"scripts/{name} 少了可执行位"


@posix_only
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
