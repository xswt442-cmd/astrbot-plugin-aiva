"""metadata.yaml 的约定。

AstrBot 插件市场从这份文件读插件信息，版本号也在里面。字段填错不影响安装，
但插件详情页会显示成 `[MISSING: ...]`、版本更新推不出去。
"""

from __future__ import annotations

import re
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent
元数据路径 = 仓库根 / "metadata.yaml"
声明路径 = 仓库根 / "pyproject.toml"

# 项目声明支持 3.10，tomllib 要 3.11，所以用正则读那一行，不引 tomllib。
_版本行 = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_lock版本行 = re.compile(r'name = "astrbot-plugin-aiva"\nversion = "([^"]+)"', re.MULTILINE)


def _元数据() -> str:
    return 元数据路径.read_text(encoding="utf-8")


def _元数据版本() -> str:
    匹配 = re.search(r"^version:\s*(\S+)", _元数据(), re.MULTILINE)
    assert 匹配, "metadata.yaml 里找不到 version"
    return 匹配.group(1)


def _声明版本() -> str:
    匹配 = _版本行.search(声明路径.read_text(encoding="utf-8"))
    assert 匹配, "pyproject.toml 里找不到 version"
    return 匹配.group(1)


def _lock版本() -> str:
    文本 = (仓库根 / "uv.lock").read_text(encoding="utf-8")
    匹配 = _lock版本行.search(文本)
    assert 匹配, "uv.lock 里找不到本项目的版本"
    return 匹配.group(1)


def test_三处版本号一致():
    """metadata 是市场读的，pyproject 与 uv.lock 是本地与打包用的。

    对不上时市场会拒绝更新，或者本地构建出与市场不同的版本。
    """
    声明 = _声明版本()
    assert _元数据版本() == f"v{声明}"
    assert _lock版本() == 声明


def test_市场要求的字段都在():
    """少一个字段，市场详情页会显示成 `[MISSING: ...]`。"""
    文本 = _元数据()
    for 字段 in ("name:", "display_name:", "short_desc:", "desc:", "version:", "author:"):
        assert 字段 in 文本, f"metadata.yaml 缺 {字段}"


def test_分类是市场自己定的那几个():
    """填错不影响安装，只是详情页的分类标签不对。"""
    匹配 = re.search(r"^category:\s*(\S+)", _元数据(), re.MULTILINE)
    assert 匹配, "metadata.yaml 里找不到 category"
    assert 匹配.group(1) == "娱乐"


def test_声明的AstrBot版本区间合理():
    匹配 = re.search(r'astrbot_version:\s*"?([^"\n]+)"?', _元数据())
    assert 匹配, "metadata.yaml 里找不到 astrbot_version"

    区间 = 匹配.group(1).strip()
    assert 区间.startswith(">="), f"下界写成了 {区间}"
    assert "<" in 区间, f"少了上界，升级 AstrBot 后会静默失效：{区间}"
