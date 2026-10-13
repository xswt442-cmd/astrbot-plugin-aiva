"""`_名字` 必须是同步函数——它曾经是 async，调用点漏 await 后：

1. 拿到的是协程对象，**不是错误**；
2. 协程对象是真值，`or "你"` 兜底不触发；
3. f-string 把它渲染成 `<coroutine object Main.名字 at 0x7fa...>`；
4. 这串东西被塞进 PK 提示词，模型把它当成玩家名字，一本正经地
   点评「`<coroutine object>`的9.4场均死亡就是铁证」。

线上实拍，2026-10-14 00:40。模型不会对荒谬输入说不——段位缺了它编段位，
名字是协程对象它就把协程对象当名字。堵法不是求模型机灵，是让这类值
根本产生不出来：函数没有 await 就不该是 async。
"""

from __future__ import annotations

import ast
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent
主源码 = (仓库根 / "main.py").read_text(encoding="utf-8")
树 = ast.parse(主源码)


def _函数(名: str):
    for n in ast.walk(树):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 名:
            return n
    raise AssertionError(f"main.py 里找不到 {名}")


class Test名字是同步的:
    def test_不是协程函数(self):
        节点 = _函数("_名字")
        assert isinstance(节点, ast.FunctionDef), (
            "_名字 必须是普通同步函数。它体内没有任何 await，做成协程只会"
            "引来「调用点漏 await → 拿到协程对象 → 真值 → 塞进提示词」"
            "这条静默故障链。"
        )

    def test_体内没有await(self):
        """如果未来真加了 await（要 async 化），上面那条测试的注释就得改，
        调用点也全部要 await——这两件事必须一起做。"""
        节点 = _函数("_名字")
        assert not any(isinstance(n, ast.Await) for n in ast.walk(节点))

    def test_调用点没有裸调用(self):
        """`self._名字(event)` 后面必须直接被 await，或本来就是同步调用。

        这里按「_名字 是同步函数」的前提检查：调用结果不许再被 await
        （await 一个非协程会 TypeError），也不许不做任何处理就进 f-string。
        """
        源码 = 主源码
        for n in ast.walk(树):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_名字"
            ):
                父 = None
                # 找到直接外层：await 自Wrapped 则说明当协程用了
                # （同步函数被 await 是运行时错误，直接禁掉）
                for 外 in ast.walk(树):
                    if isinstance(外, ast.Await) and 外.value is n:
                        父 = 外
                assert 父 is None, (
                    f"main.py 第 {n.lineno} 行 await 了同步函数 _名字，会 TypeError"
                )


class Test提示词防线:
    def test_名字兜底在PK里仍然存在(self):
        """`or "你"` 这个兜底要留着，但它是防「平台没给名字」，
        不是防协程对象——协程对象的防线在上面那条测试里。"""
        源码 = 主源码
        assert 'or "你"' in 源码


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
