"""`main.py` 的接线检查。

`main.py` 跑不了单测——它顶层 import astrbot，本地没这个包。所以下面这些
只能查源码。改 `main.py` 时这些检查要跟着一起过。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aiva.兜底 import 子命令名

源码目录 = Path(__file__).resolve().parent.parent
main源 = 源码目录 / "main.py"


def _树() -> ast.Module:
    return ast.parse(main源.read_text(encoding="utf-8"))


def _类() -> ast.ClassDef:
    for 节点 in _树().body:
        if isinstance(节点, ast.ClassDef) and 节点.name == "Main":
            return 节点
    raise AssertionError("main.py 里没有 Main 类")


def _指令名() -> set[str]:
    """类体里 `@爱瓦.command("x", alias={...})` 声明的全部名字与别名。"""
    出: set[str] = set()
    for 节点 in _类().body:
        for 装饰 in 节点.decorator_list:
            if not isinstance(装饰, ast.Call) or "command" not in ast.unparse(装饰.func):
                continue
            if 装饰.args and isinstance(装饰.args[0], ast.Constant):
                出.add(str(装饰.args[0].value))
            for 关键字 in 装饰.keywords:
                if 关键字.arg == "alias" and isinstance(关键字.value, ast.Set):
                    出.update(str(e.value) for e in 关键字.value.elts)
    return 出


class Test组名:
    def test_组名是爱瓦(self):
        常量 = {
            目标.targets[0].id: 目标.value.value
            for 目标 in _树().body
            if isinstance(目标, ast.Assign)
            and isinstance(目标.targets[0], ast.Name)
            and isinstance(目标.value, ast.Constant)
        }
        assert 常量.get("_组名") == "爱瓦"

    def test_兜底过滤器用同一个组名(self):
        文本 = main源.read_text(encoding="utf-8")
        assert "是否落空(文本, _组名)" in 文本


class Test兜底同步:
    def test_每个指令都在兜底名单里(self):
        # 落一个别名没同步，用户打那个别名就会被当成废话，
        # 拿到一句「不是子命令」。
        缺 = _指令名() - 子命令名
        assert not 缺, f"这些指令/别名没写进 兜底.子命令名：{sorted(缺)}"

    def test_提示里提到的指令都真实存在(self):
        文本 = main源.read_text(encoding="utf-8")
        帮助块 = 文本.split("_帮助文本")[1].split('"""')[1]
        for 词 in ("绑定", "战绩", "锐评", "PK", "开一局", "解绑", "状态"):
            assert f"/爱瓦 {词}" in 帮助块, f"帮助里缺 /爱瓦 {词}"


def _日志调用() -> list[str]:
    """把 main.py 里所有 `logger.xxx(...)` 的内容源码抠出来。"""
    出: list[str] = []
    for 节点 in ast.walk(_树()):
        if not isinstance(节点, ast.Call):
            continue
        函数 = 节点.func
        if isinstance(函数, ast.Attribute) and getattr(函数.value, "id", "") == "logger":
            出.extend(ast.unparse(参数) for 参数 in 节点.args)
    return 出


class Test凭据不外泄:
    def test_日志里不带凭据字段(self):
        # 换票时把 openid/access_token 传给 transport 是必需的，不算泄。
        # 泄的是把它写进 logger——日志会被到处收集、分发。
        for 参数 in _日志调用():
            for 敏感 in ("access_token", "openid", "tid", "凭据["):
                assert 敏感 not in 参数, f"日志带上了凭据字段：{参数}"

    def test_日志里不会出现整个凭据对象(self):
        # 直接把 dict 丢进 f-string 会把四样全打印出来。
        for 参数 in _日志调用():
            assert not any(f"{{{名}}}" in 参数 for 名 in ("凭据",))


class Test导入齐全:
    @pytest.mark.parametrize(
        "名字",
        [
            "扫码会话",
            "开局设定",
            "设定文本",
            "找对手",
            "PK提示",
            "开局提示",
            "锐评提示",
            "占优项数",
            "对比文本",
            "对比要点",
            "聚合",
            "近况文本",
            "凭据仓库",
            "凭据摘要",
            "凭据是否齐全",
            "业务错误",
            "登录过期",
            "掌瓦传输",
            "取落空参数",
            "是否落空",
            "落空提示",
        ],
    )
    def test_用到的符号在导入段出现过(self, 名字: str):
        文本 = main源.read_text(encoding="utf-8")
        assert 名字 in 文本
