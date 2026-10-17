"""日志里不能出现登录态材料。

市场审核把「token 进日志」判为泄漏，**连片段都算**。换票体里的 `sig` 就是
access_token，跳转链 URL 里带 `keystr` / `ptsigx` / `code`，这些一旦写进日志，
等于在磁盘上留一份可复用的凭据。
"""

from __future__ import annotations

from aiva.auth.ptlogin import 脱敏
from aiva.transport import _体摘要


class Test请求体摘要:
    def test_换票体不打值(self):
        体 = {
            "login_info": {
                "appid": "1001",
                "openid": "OPENID_SECRET",
                "sig": "ACCESS_TOKEN_SECRET",
                "uin": 0,
            }
        }
        摘要 = _体摘要(体)

        assert "OPENID_SECRET" not in 摘要
        assert "ACCESS_TOKEN_SECRET" not in 摘要
        assert "login_info" in 摘要, "字段名要留着，不然排查分不清请求长什么样"

    def test_普通字段也不打值(self):
        """只保留字段名是硬规则：白名单一漏就是一次泄漏。"""
        摘要 = _体摘要({"mcode": "MCODE_SECRET", "page": 1})

        assert "MCODE_SECRET" not in 摘要
        assert "mcode" in 摘要


class Test轨迹脱敏:
    def test_跳转链里的密钥被抹掉(self):
        轨迹 = 脱敏(
            "https://ssl.ptlogin2.qq.com/check?uin=123&ptsigx=PTSIGX_SECRET&code=CODE_SECRET"
        )

        assert "PTSIGX_SECRET" not in 轨迹
        assert "CODE_SECRET" not in 轨迹

    def test_json_形态也抹(self):
        脱敏后 = 脱敏('{"access_token": "TOKEN_SECRET", "openid": "OPENID_SECRET"}')

        assert "TOKEN_SECRET" not in 脱敏后
        assert "OPENID_SECRET" not in 脱敏后

    def test_回调地址抹(self):
        脱敏后 = 脱敏("auth://tauth.qq.com/?#access_token=TOKEN_SECRET&openid=OPENID_SECRET")

        assert "TOKEN_SECRET" not in 脱敏后
        assert "OPENID_SECRET" not in 脱敏后

    def test_普通文本不动(self):
        assert 脱敏("第2跳 302 无下一跳") == "第2跳 302 无下一跳"
