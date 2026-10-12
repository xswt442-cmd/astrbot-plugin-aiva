"""依赖清单的约束。

AstrBot 安装插件时把 requirements.txt 喂给 pip，而 pip 装在同一环境里，
装的就是 AstrBot 核心自己的依赖。核心给这些包装了版本护栏：插件若要求一个
与核心不同的精确版本，护栏会拦下 pip，安装整体失败。

`uv export` 恰好会把每个包钉成 `==`，正是触发护栏的写法。所以这个文件
必须手写。这里把三条约束钉住：

1. 不能出现 `==` 精确钉版本
2. 直接依赖要与 pyproject.toml 的 dependencies 对得上
3. 不能是 uv export 的产物
"""

from __future__ import annotations

import re
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent
清单路径 = 仓库根 / "requirements.txt"
声明路径 = 仓库根 / "pyproject.toml"

# 只取真正写依赖的行，注释和空行不算。
_依赖行 = re.compile(r"^[A-Za-z0-9_.\-]+")

# 项目声明支持 3.10，而 tomllib 要 3.11，所以这里不引 tomllib，
# 只需要 dependencies 那一段的包名，正则读比解析 TOML 省事。
_依赖段 = re.compile(r"^dependencies\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)


def _读清单() -> list[str]:
    return [
        行.strip()
        for 行 in 清单路径.read_text(encoding="utf-8").splitlines()
        if 行.strip() and not 行.strip().startswith("#")
    ]


def _读声明() -> list[str]:
    段 = _依赖段.search(声明路径.read_text(encoding="utf-8"))
    assert 段, "pyproject.toml 里找不到 dependencies"
    # 一行一项。不能按逗号切：版本范围里自带逗号（>=3.9,<5），切开会断。
    return [
        条.strip().strip(",").strip('"').strip("'")
        for 条 in 段.group(1).splitlines()
        if 条.strip().strip(",").strip('"').strip("'")
    ]


def test_没有精确钉版本():
    """`==` 会和核心的版本护栏撞车，pip 动不了核心的包就装不上。"""
    钉死的 = [行 for 行 in _读清单() if "==" in 行]
    assert not 钉死的, f"requirements.txt 不能钉死版本，会和核心冲突：{钉死的}"


def test_不是_uv_export_的产物():
    """uv export 的文件头会这么写。看到这句就说明有人改回自动生成了。"""
    assert "uv 自动生成" not in 清单路径.read_text(encoding="utf-8")


def test_直接依赖与_pyproject_一致():
    """两个文件各服务一头：pyproject 给本地 uv sync，本清单给 AstrBot 的 pip。"""
    清单名 = {_依赖行.match(行).group() for 行 in _读清单()}
    声明名 = {_依赖行.match(行).group() for 行 in _读声明()}
    assert 清单名 == 声明名, (
        f"两边不一致。requirements.txt: {sorted(清单名)}，pyproject.toml: {sorted(声明名)}"
    )


def test_范围约束不是空的():
    """每一行都要有版本下界，否则 pip 可能把核心的包换成任意版本。"""
    for 行 in _读清单():
        assert re.search(r"[><=]+[0-9]", 行), f"缺少版本约束：{行}"


def test_下界跟着核心走():
    """清单的下界对齐 AstrBot 核心的声明，比 pyproject 更严是可以的。

    核心要求 aiohttp>=3.11.18，本地开发按 >=3.9 也行，但装进容器时按核心的
    下界写才不会让 pip 去动核心的包。所以允许清单更严，不允许更松。
    """

    def _下界(约束: str) -> tuple[int, ...]:
        匹配 = re.search(r">=\s*([0-9.]+)", 约束)
        return tuple(int(x) for x in 匹配.group(1).split(".")) if 匹配 else ()

    清单 = {行.split(">")[0].split("<")[0].strip(): 行 for 行 in _读清单()}
    for 声明 in _读声明():
        包, _, 约束 = 声明.partition(">")
        assert _下界(清单[包]) >= _下界(约束), (
            f"{包} 在 requirements.txt 里的下界比 pyproject.toml 松，装插件时 pip 可能去动核心的包"
        )
