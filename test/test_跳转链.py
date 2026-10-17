"""跳转链的解析逻辑：腾讯这套登录链的「下一跳」不总是 302。

线上事故（2026-10-13 17:41）：扫码成功了，腾讯回 `code=0`，给出的地址是
`http://ptlogin4.openmobile.qq.com/check_sig?...&ptsigx=...`。我们把这一跳
请求回来之后什么凭据都没捞到，因为 `_追跳转` 只认两种形状：
HTTP `Location` 头，和正文里的 `auth://tauth.qq.com/...`。
`check_sig` 返回的既不是 302 也不是 auth://，于是直接断链。

这些测试只测纯函数（`_正文里的下一跳`、`_从地址提凭据`），不碰网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aiva.auth.ptlogin import _从地址提凭据, _可以跟跳, _正文里的下一跳, 扫码会话


class Test正文里的下一跳:
    @pytest.mark.parametrize(
        ("正文", "期望"),
        [
            # 最常见的两种 JS 跳转
            (
                """<script>location.href="http://ptlogin2.graph.qq.com/ck/x?a=1"</script>""",
                "http://ptlogin2.graph.qq.com/ck/x?a=1",
            ),
            (
                """location.replace('https://xui.ptlogin2.qq.com/next')""",
                "https://xui.ptlogin2.qq.com/next",
            ),
            ('window.location = "http://a.com/b"', "http://a.com/b"),
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

        源码 = (Path(__file__).resolve().parent.parent / "aiva" / "auth" / "ptlogin.py").read_text(
            encoding="utf-8"
        )
        assert "最多: int = 12" in 源码
        assert "_记轨迹" in 源码


class Test拼openlogin_data:
    """漏了 pt_openlogin_data，腾讯会回 code=0 但拿不到 token。

    这是整条链路最阴的坑：没有任何报错，只是静默少一半信息。
    """

    @pytest.mark.asyncio
    async def test_拼出29项(self):
        import aiohttp

        from aiva.auth.ptlogin import _拼openlogin_data

        会话 = 扫码会话()
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as 裸:
            会话._会话 = 裸
            数据 = _拼openlogin_data(会话)
        字段 = dict(pair.split("=", 1) for pair in 数据.split("&"))
        # 31 项：which/refer_cgi/.../loginty。少一项腾讯就少一半信息。
        assert len(字段) == 31, f"openlogin_data 字段数变了：{len(字段)}"
        assert 字段["openapi"] == "1011"
        assert 字段["has_auth"] == "1"
        assert 字段["update_auth"] == "1"
        assert 字段["page_type"] == "1"
        assert 字段["pf"] == "openmobile_android"
        assert 字段["response_type"] == "token"
        assert 字段["redirect_uri"].startswith("auth%3A%2F%2Ftauth.qq.com")
        assert 字段["client_id"] == "102061775"

    @pytest.mark.asyncio
    async def test_从xlogin查询串回读(self):
        """refer_cgi / sdkv / h5sig 等要跟 xlogin 的参数对齐。"""
        import aiohttp

        from aiva.auth.ptlogin import _拼openlogin_data

        会话 = 扫码会话()
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as 裸:
            会话._会话 = 裸
            字段 = dict(p.split("=", 1) for p in _拼openlogin_data(会话).split("&"))
        assert 字段["refer_cgi"] == "m_authorize"
        assert 字段["sdkv"] == "3.5.17.lite"
        assert 字段["loginty"] == "6"
        assert 字段["status_os"] == "12"

    def test_轮询必须带上它(self):
        from pathlib import Path

        源码 = (Path(__file__).resolve().parent.parent / "aiva" / "auth" / "ptlogin.py").read_text(
            encoding="utf-8"
        )
        assert '"pt_openlogin_data": self._openlogin_data' in 源码


class Test提登录sig:
    def test_优先取页面里的(self):
        from aiva.auth.ptlogin import _提登录_sig

        页面 = 'g_login_sig=encodeURIComponent("abc%2Fdef")'
        assert _提登录_sig(页面, 扫码会话()) == "abc/def"

    def test_页面没有就退化到cookie(self):
        from aiva.auth.ptlogin import _提登录_sig

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": "from-cookie"  # type: ignore[method-assign]
        assert _提登录_sig("没有这一行", 类) == "from-cookie"

    def test_都没有就空串(self):
        from aiva.auth.ptlogin import _提登录_sig

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": ""  # type: ignore[method-assign]
        assert _提登录_sig("", 类) == ""


class Test收密钥候选:
    def test_从查询串收(self):
        from aiva.auth.ptlogin import _收密钥候选

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": ""  # type: ignore[method-assign]
        地址 = "https://x.com/y?keystr=KEY123&other=1"
        候选 = _收密钥候选(类, 地址)
        assert ("KEY123", "url:keystr") in 候选

    def test_从fragment收(self):
        from aiva.auth.ptlogin import _收密钥候选

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": ""  # type: ignore[method-assign]
        候选 = _收密钥候选(类, "https://x.com/y#redirect_uri_key=FRAGKEY")
        assert ("FRAGKEY", "url:redirect_uri_key") in 候选

    def test_六个同义字段都认(self):
        from aiva.auth.ptlogin import _密钥字段名, _收密钥候选

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": ""  # type: ignore[method-assign]
        for 名 in _密钥字段名:
            候选 = _收密钥候选(类, f"https://x.com/y?{名}=V-{名}")
            assert (f"V-{名}", f"url:{名}") in 候选, f"{名} 没被收进来"

    def test_去重(self):
        from aiva.auth.ptlogin import _收密钥候选

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": ""  # type: ignore[method-assign]
        地址 = "https://x.com/y?keystr=SAME&key=SAME"
        候选 = _收密钥候选(类, 地址)
        assert len([c for c in 候选 if c[0] == "SAME"]) == 1

    def test_从cookie收(self):
        from aiva.auth.ptlogin import _收密钥候选

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": "CK" if 名字 == "keystr" else ""  # type: ignore[method-assign]
        候选 = _收密钥候选(类, "")
        assert any(v == "CK" for v, _ in 候选)

    def test_什么都没有就返回空(self):
        from aiva.auth.ptlogin import _收密钥候选

        类 = 扫码会话()
        类._取cookie = lambda 名字, 域="": ""  # type: ignore[method-assign]
        assert _收密钥候选(类, "") == []


class Test提auth回调:
    def test_读Callback包装的JSON(self):
        from aiva.auth.ptlogin import _提auth回调

        正文 = '_Callback({"url":"auth://tauth.qq.com/?#access_token=T&openid=O"});'
        回调 = _提auth回调(正文)
        assert 回调.startswith("auth://")
        assert "access_token=T" in 回调

    def test_JSON坏了退回正则(self):
        from aiva.auth.ptlogin import _提auth回调

        正文 = "_Callback({坏掉的 JSON); auth://tauth.qq.com/?#access_token=T&openid=O"
        回调 = _提auth回调(正文)
        assert 回调.startswith("auth://")

    def test_URL字段不是auth开头就不要(self):
        from aiva.auth.ptlogin import _提auth回调

        assert _提auth回调('_Callback({"url":"https://evil.com"});') == ""

    @pytest.mark.parametrize("正文", ["", "什么都没有"])
    def test_没回调返回空(self, 正文: str):
        from aiva.auth.ptlogin import _提auth回调

        assert _提auth回调(正文) == ""


class Test换回调链路:
    def test_地址是openmobile不带4(self):
        """`openmobile.qq.com` 能正常解析；带 4 的那个在内网被屏蔽。"""
        from aiva.auth.ptlogin import _换回调地址

        assert _换回调地址 == "https://openmobile.qq.com/oauth2.0/m_get_redirect_url"

    def test_用密钥换凭据被调用(self):
        """跟完跳转没有 token 时必须走换回调这条路，不能直接抛错。"""
        from pathlib import Path

        源码 = (Path(__file__).resolve().parent.parent / "aiva" / "auth" / "ptlogin.py").read_text(
            encoding="utf-8"
        )
        assert "await self._用密钥换凭据(跳转)" in 源码, "必须在抛错前先尝试换回调"


class Test跳转只许腾讯域:
    """会话里带着 cookie，跟着任意 Location 走等于把登录态交给对方。

    腾讯会换子域（ptlogin2 / ptlogin4 / xui / graph…），枚举主机名跟不上，
    所以按后缀 `*.qq.com` 判。
    """

    @pytest.mark.parametrize(
        "地址",
        [
            "https://xui.ptlogin2.qq.com/cgi-bin/xlogin",
            "http://ptlogin4.openmobile.qq.com/check_sig?ptsigx=1",
            "https://ssl.ptlogin2.qq.com/check?uin=1",
            "https://connect.qq.com/",
            "https://QQ.COM/a",
        ],
    )
    def test_腾讯域放行(self, 地址):
        assert _可以跟跳(地址)

    @pytest.mark.parametrize(
        "地址",
        [
            "https://evil.com/",
            "https://qq.com.evil.com/",  # 后缀伪装
            "https://notqq.com/",
            "http://127.0.0.1:8080/",
            "file:///etc/passwd",
            "",
        ],
    )
    def test_非腾讯域拒绝(self, 地址):
        assert not _可以跟跳(地址)

    def test_追跳转里真的会拦(self):
        源码 = Path(__file__).resolve().parent.parent / "aiva" / "auth" / "ptlogin.py"
        源 = 源码.read_text(encoding="utf-8")
        assert "_可以跟跳(下一位)" in 源, "拿到了下一跳却没用白名单判，等于没有拦"
