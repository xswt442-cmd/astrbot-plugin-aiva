"""扫码链路的超时与网络异常不许穿透到 handler。

线上事故：用户在扫码等待期间发了句别的消息，`aiohttp` 的 `sock_connect`
被打断抛 `asyncio.TimeoutError`，它穿过 `_追跳转` → `轮询一次` → `绑定`，
最后框架在群里弹出「在调用插件 astrbot_plugin_aiva 的处理函数 绑定 时出现
异常」加一大段 traceback。用户只看到一句「在吗」把绑定搞挂了。

这些测试不import `main.py`（顶层 import astrbot，本地跑不了），
只测 `aiva.auth.ptlogin` 里的纯逻辑与异常边界。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
import pytest

from aiva.auth.ptlogin import 扫码会话

源码 = (Path(__file__).resolve().parent.parent / "aiva" / "auth" / "ptlogin.py").read_text(
    encoding="utf-8"
)


class _假响应:
    """够用的最小 aiohttp 响应替身。"""

    def __init__(self, 正文: str = "", 头: dict[str, str] | None = None):
        self._正文 = 正文
        self.headers = 头 or {}
        self.status = 200

    async def text(self, errors: str = "strict") -> str:
        return self._正文

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _假会话:
    """按 URL 决定抛什么或返回什么。"""

    def __init__(self, 行为: dict[str, object]):
        self._行为 = 行为
        self.请求过: list[str] = []

    def get(self, url: str, **kwargs):
        self.请求过.append(url)
        结果 = self._行为.get(url, _假响应(""))
        if isinstance(结果, BaseException):
            raise 结果
        if callable(结果):
            return 结果(url, **kwargs)
        return 结果

    async def close(self) -> None:
        return None


class Test追跳转不穿透异常:
    @pytest.mark.parametrize(
        "异常",
        [
            TimeoutError(),
            asyncio.TimeoutError(),
            aiohttp.ClientError("boom"),
            ConnectionResetError("reset"),
            OSError("network unreachable"),
        ],
    )
    async def test_单跳异常返回None而不是抛出(self, 异常):
        """任何网络异常都按「这一跳没拿到」处理，返回 None 等下一轮。"""
        会话 = 扫码会话()
        会话._会话 = _假会话({"https://x.example/1": 异常})

        结果 = await 会话._追跳转("https://x.example/1")

        assert 结果 is None, f"{type(异常).__name__} 穿透了 _追跳转"

    async def test_首跳失败后不再继续(self):
        """失败就停，别拿同一个坏连接连打 5 次。"""
        会话 = 扫码会话()
        假 = _假会话({"https://a": TimeoutError(), "https://b": _假响应("")})
        会话._会话 = 假

        assert await 会话._追跳转("https://a") is None
        assert 假.请求过 == ["https://a"], f"不该继续请求：{假.请求过}"

    async def test_响应读取时才异常也能吞掉(self):
        """异常发生在 `async with` 内部（读正文时）同样不能穿透。"""

        class _读炸的响应(_假响应):
            async def __aenter__(self):
                return self

            async def text(self, errors: str = "strict") -> str:
                raise asyncio.TimeoutError()

        会话 = 扫码会话()
        会话._会话 = _假会话({"https://x.example/1": _读炸的响应()})

        assert await 会话._追跳转("https://x.example/1") is None

    async def test_会话为None时直接返回(self):
        会话 = 扫码会话()
        assert await 会话._追跳转("https://x.example/1") is None


class Test跳转超时预算:
    def test_每一跳都有独立超时(self):
        """会话的 total=20 是单条请求预算，跳转链最多 5 跳，不单独设就是 100 秒。

        实测正是这里出的事：等100 秒期间用户发消息打断连接。
        """
        assert "_跳转超时" in 源码
        assert "timeout=aiohttp.ClientTimeout(total=_跳转超时)" in 源码

    def test_单跳超时给够用(self):
        """腾讯登录单跳实测约 3 秒，`m_get_redirect_url` 也在 12 秒内，
        5 秒太紧会把本来能成的跳转掐死。"""
        from aiva.auth.ptlogin import _跳转超时

        assert _跳转超时 >= 10, f"单跳 {_跳转超时} 秒不够腾讯登录接口用"

    def test_捕获列表含超时(self):
        assert "except (TimeoutError, aiohttp.ClientError, OSError)" in 源码, (
            "网络异常必须被吃掉，不许穿透到 handler"
        )


class Test轮询异常归类:
    def test_绑定接住超时(self):
        """handler 里必须有 `except asyncio.TimeoutError`。"""
        主 = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        assert "except asyncio.TimeoutError:" in 主, "绑定没接住超时，会炸成插件异常"

    def test_出码与换票都有兜底(self):
        """任何异常都要翻译成人话，不能冒到框架手上弹 traceback。"""
        主 = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        绑定块 = 主.split("async def 绑定")[1].split("@爱瓦.command")[0]
        # 出码、换票各一个宽泛兜底；轮询处是专门的 asyncio.TimeoutError
        assert 绑定块.count("except Exception") >= 2, (
            f"出码 / 换票 两处都该有兜底，实际 {绑定块.count('except Exception')} 处"
        )
        assert "except asyncio.TimeoutError:" in 绑定块, "轮询处没接住超时"
