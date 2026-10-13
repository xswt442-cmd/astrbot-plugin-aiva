"""`main.py` 的接线检查。

`main.py` 跑不了单测——它顶层 import astrbot，本地没这个包。所以下面这些
只能查源码。改 `main.py` 时这些检查要跟着一起过。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aiva.兜底 import 以组名开头, 取落空参数, 子命令名, 是否落空

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

    def test_兜底过滤器恒返回True(self):
        """`CustomFilter.filter` 返回 False 会让整个指令组被跳过。

        AstrBot 的 `CommandGroupFilter.filter` 里是
        `if not self.custom_filter_ok(...): return False`——返回值的语义是
        「这条消息我管不管」，不是「命中没有」。所以兜底过滤器**所有出口
        都必须 return True**：命中就自己 set_result + stop_event，
        不属于我的消息要立刻放行。写成「命中返回 False」时 `/爱瓦 绑定`
        完全没反应。
        """
        方法 = _兜底过滤器()
        返回 = [
            节点.value.value
            for 节点 in ast.walk(方法)
            if isinstance(节点, ast.Return) and isinstance(节点.value, ast.Constant)
        ]
        assert 返回 and set(返回) == {True}, f"兜底 filter 里出现了 {返回}，必须只return True"
        # 命中分支必须 set_result + stop_event，否则消息会漏给模型
        assert "event.stop_event()" in ast.unparse(方法)
        # 必须先判「关不关我事」再动手，否则会掐掉别的插件的指令
        assert "以组名开头" in ast.unparse(方法)


def _兜底过滤器() -> ast.FunctionDef:
    for 节点 in _树().body:
        if isinstance(节点, ast.ClassDef) and 节点.name == "_落空兜底":
            for 体 in 节点.body:
                if isinstance(体, ast.FunctionDef) and 体.name == "filter":
                    return 体
    raise AssertionError("main.py 里没有 _落空兜底.filter")


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


class Test兜底不越界:
    """兜底过滤器绝不能碰别人的消息。

    `CommandGroupFilter.filter` 先跑 `custom_filter_ok()`、之后才检查组名，
    所以挂在指令组上的过滤器对**每一条消息**都执行。原实现里
    `取落空参数` 对不属于自己的消息原样返回，导致「爱农 状态」被当成
    「爱瓦的子命令落空」而`stop_event()` —— 爱农因此从能用变成完全没反应。
    """

    @pytest.mark.parametrize(
        "消息",
        [
            "爱农 状态",
            "/爱农 绑定",
            "爱wm PK 76561198412825279",
            "帮助",
            "",
            "今天天气不错",
            "爱瓦",
        ],
    )
    def test_别人的消息不判定为落空(self, 消息: str):
        assert not 是否落空(消息, "爱瓦"), f"{消息!r} 被误判成爱瓦的落空"

    @pytest.mark.parametrize("消息", ["爱瓦 瞎写的", "/爱瓦 瞎写的"])
    def test_爱瓦的瞎写才算落空(self, 消息: str):
        assert 是否落空(消息, "爱瓦"), f"{消息!r} 应该判成落空但没有"

    @pytest.mark.parametrize(
        "消息",
        ["爱瓦 绑定", "/爱瓦 绑定", "爱瓦战绩", "爱瓦 PK", "爱瓦 help"],
    )
    def test_爱瓦的正常指令不算落空(self, 消息: str):
        assert not 是否落空(消息, "爱瓦"), f"{消息!r} 是正常指令，不该被判成落空"

    def test_取落空参数对陌生消息返回空(self):
        # 返回原样文本是上一版 bug 的根源：调用方无从分辨「不归我管」
        assert 取落空参数("爱农 状态", "爱瓦") == ""
        assert 取落空参数("爱瓦 瞎写的", "爱瓦") == "瞎写的"

    def test_以组名开头(self):
        assert 以组名开头("爱瓦 绑定", "爱瓦")
        assert 以组名开头("/爱瓦 绑定", "爱瓦")
        assert not 以组名开头("爱农 绑定", "爱瓦")
        assert not 以组名开头("", "爱瓦")


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
