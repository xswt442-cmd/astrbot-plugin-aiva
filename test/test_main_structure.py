"""`main.py` 结构层的约束。

这些检查存在是因为**本地测试看不到它们**：`main.py` 顶层 import astrbot，
本地没有这个包，所以只能查源码。下面两条都是在容器里真加载时才炸出来的东西。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

main源 = Path(__file__).resolve().parent.parent / "main.py"


def _树() -> ast.Module:
    return ast.parse(main源.read_text(encoding="utf-8"))


def _Main类() -> ast.ClassDef:
    for 节点 in _树().body:
        if isinstance(节点, ast.ClassDef) and 节点.name == "Main":
            return 节点
    raise AssertionError("main.py 里没有 Main 类")


def _指令方法() -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    return [
        节点 for 节点 in _Main类().body if isinstance(节点, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]


def test_异步生成器里不许_return_带值():
    """AstrBot 的指令是异步生成器（`yield event.plain_result(...)`）。

    在同一个函数里既要 `yield` 又要 `return <值>`，Python 直接
    `SyntaxError: 'return' with value in async generator`——**而且是在插件导入
    时才报**，本地 `pytest` 一行都跑不到，只能等装进容器看日志才发现。

    第一版就是这么挂的：`_取近期战绩` 一边 `yield` 错误提示，一边
    `return (文本, 摘要)`。改成了抛 `这句给用户`。别改回去。
    """
    for 方法 in _指令方法():
        有yield = any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(方法))
        if not 有yield:
            continue
        for n in ast.walk(方法):
            if not isinstance(n, ast.Return) or n.value is None:
                continue
            # `return` 与 `return None` 是合法的提前退出，只有带别的值不行。
            if isinstance(n.value, ast.Constant) and n.value.value is None:
                continue
            pytest.fail(
                f"{方法.name} 第 {n.lineno} 行：异步生成器里不能 return 带值，"
                "插件导入时会 SyntaxError。要么抛异常，要么拆成两个函数。"
            )


def test_这句给用户存在且被用到():
    """这个异常是「不是故障、但要告诉用户」的统一出口，别绕开它自己 return。"""
    类体 = {n.name for n in _Main类().body if isinstance(n, ast.ClassDef)}
    顶层 = {n.name for n in _树().body if isinstance(n, ast.ClassDef)}
    assert "这句给用户" in 类体 or "这句给用户" in 顶层


@pytest.mark.parametrize("名字", ["战绩", "锐评", "PK", "开一局", "绑定", "解绑", "状态"])
def test_指令都是异步生成器(名字: str):
    """指令要把结果 `yield` 出去，写 `return` 的结果用户收不到。"""
    方法 = next((m for m in _指令方法() if m.name == 名字), None)
    assert 方法 is not None, f"没有 {名字} 指令"
    if 名字 == "_名字":
        return
    assert any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(方法)), (
        f"{名字} 里没有 yield，结果发不出去"
    )
