"""跳转链的解析逻辑：腾讯这套登录链的「下一跳」不总是 302。

线上事故（2026-10-13 17:41）：扫码成功了，腾讯回 `code=0`，给出的地址是
`http://ptlogin4.openmobile.qq.com/check_sig?...&ptsigx=...`。我们把这一跳
请求回来之后什么凭据都没捞到，因为 `_追跳转` 只认两种形状：
HTTP `Location` 头，和正文里的 `auth://tauth.qq.com/...`。
`check_sig` 返回的既不是 302 也不是 auth://，于是直接断链。

这些测试只测纯函数（`_正文里的下一跳`、`_从地址提凭据`），不碰网络。
"""

from __future__ import annotations

import pytest

from aiva.auth.ptlogin import _从地址提凭据, _正文里的下一跳, 扫码结果


class Test正文里的下一跳:
    @pytest.mark.parametrize(
        ("正文", "期望"),
        [
            # 最常见的两种 JS 跳转
            ("""<script>location.href="http://ptlogin2.graph.qq.com/ck/x?a=1"</script>""",
             "http://ptlogin2.graph.qq.com/ck/x?a=1"),
            ("""location.replace('https://xui.ptlogin2.qq.com/next')""",
             "https://xui.ptlogin2.qq.com/next"),
            ("window.location = \"http://a.com/b\"", "http://a.com/b"),
            ("location.assign('http://a.com/c')", "http://a.com/c"),
            # meta refresh
            ('<meta http-equiv="refresh" content="0;url=http://a.com/d">', "http://a.com/d"),
            # 转义过的 & 和 / 必须还原，否则拼出来的 URL 少参数
            ('location.href="http://a.com/e?x=1\\x26y=2"', "http://a.com/e?x=1&y=2"),
            ('location.href="http:\\/\\/a.com\\/f"', "http://a.com/f"),
        ],
    )
    def test_认得各种下一跳形状(self, 正文: str, 期望: str):
        assert _正文里的下一跳(正文) == 期望

    @pytest.mark.parametrize(
        "正文",
        [
            "",
            "<html><body>没有跳转</body></html>",
            'location.href="about:blank"',
            'location.href="javascript:void(0)"',
            'location.href="#"',
        ],
    )
    def test_不是下一跳的就别返回(self, 正文: str):
        assert _正文里的下一跳(正文) == ""

    def test_取第一个出现的跳转(self):
        正文 = """location.href="http://a.com/first";location.href="http://a.com/second";"""
        assert _正文里的下一跳(正文) == "http://a.com/first"


class Test从地址提凭据:
    def test_读标准auth回调(self):
        回调 = "auth://tauth.qq.com/?#access_token=AT123&openid=OID456"
        结果 = _从地址提凭据(回调)
        assert 结果 is not None
        assert 结果.openid == "OID456"
        assert 结果.access_token == "AT123"

    def test_从正文里挖出auth回调(self):
        正文 = """<script>location.href="auth://tauth.qq.com/?#access_token=T&openid=O"</script>"""
        结果 = _从地址提凭据(正文)
        assert 结果 is not None
        assert 结果.openid == "O"
        assert 结果.access_token == "T"

    def test_缺token就不算凭据(self):
        assert _从地址提凭据("auth://tauth.qq.com/?#openid=OID456") is None

    def test_缺openid就不算凭据(self):
        assert _从地址提凭据("auth://tauth.qq.com/?#access_token=AT123") is None

    @pytest.mark.parametrize("文本", ["", "没有任何凭据的一段文字", "http://a.com/x?y=1"])
    def test_无关文本返回none(self, 文本: str):
        assert _从地址提凭据(文本) is None

    def test_还原转义过的大写转义(self):
        正文 = 'location.href="auth://tauth.qq.com/?#access_token=T\\u0026openid=O"'
        结果 = _从地址提凭据(正文)
        assert 结果 is not None
        assert 结果.openid == "O"
        assert 结果.access_token == "T"


class Test会话留轨迹:
    def test_轨迹属性初始为空(self):
        from aiva.auth.ptlogin import 扫码会话

        assert 扫码会话().跳转轨迹 == []

    def test_会话源码里记录了每跳(self):
        """跳数要够。check_sig 之后往往还要再跳两三次。"""
        from pathlib import Path

        源码 = (
            Path(__file__).resolve().parent.parent / "aiva" / "auth" / "ptlogin.py"
        ).read_text(encoding="utf-8")
        assert "最多: int = 12" in 源码
        assert "_记轨迹" in 源码