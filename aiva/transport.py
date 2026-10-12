"""掌上无畏契约（掌瓦）接口客户端。

国服没有玩家可读的公开 API：Riot 官方 API 只覆盖国际服，`api.riotgames.cn`、
`pd.cn.a.pvp.net` 实测 DNS 无记录。能拿到国服战绩的只有腾讯官方 App
「掌上无畏契约」的私有接口。所以：

- 一切走 `app.mval.qq.com`，请求体是明文 JSON，**没有 XXTEA、没有 YSDK 签名**；
- 身份信息全挂在 Cookie 上（openid / access_token / userId / tid）；
- `mcode` 是硬编码的渠道串，腾讯轮换就失效——届时这里会集体报错，
  报错的文案写在 `_翻译错误` 里，别让它显示成一串数字。

响应约定：`result == 0` 才是成功，数据在 `data` 里。其余一律走错误翻译。
"""

from __future__ import annotations

import json
import ssl
import time
from typing import Any

import aiohttp

__all__ = ["掌瓦传输", "业务错误", "登录过期"]

_接口根 = "https://app.mval.qq.com"
_通用查询 = "source_game_zone=agame&game_zone=agame"

# 换了凭证（openid+token）后的三大入口。返回 999999 就是「活着但要登录」。
_登录换票 = "/go/auth/login_by_qq"
_主角色 = "/go/account/get_main_role_raw"
_对局列表 = "/go/agame/career/record/list"
_对局详情 = "/go/agame/career/record/scoreboard"

_APPID = 102061775
_MAPPID = 10200
_MCODE = "132f0a77d34402abc8463d60100011d19b0e"

_UA = (
    "mval/2.4.0.10053 Channel/10068 Manufacturer/Xiaomi "
    "Mozilla/5.0 (Linux; Android 14; 23117RK66C Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/101.0.4951.61 Mobile Safari/537.36"
)


class 业务错误(Exception):
    """接口给了非 0 的 result。消息已经翻成人话，可以直接发给用户。"""


class 登录过期(业务错误):
    """登录态失效，需要重新扫码。"""


def _不校验的SSL() -> ssl.SSLContext:
    """腾讯这套证书链在容器里偶发校验失败；这里只取数据，不涉及凭据外发。

    关掉校验是**有意**的取舍：容器里的 CA 根证书经常比 App 侧的证书旧，
    开着会让整条链路随机失败。这里只 GET/POST 自己的战绩数据。
    """
    上下文 = ssl.create_default_context()
    上下文.check_hostname = False
    上下文.verify_mode = ssl.CERT_NONE
    return 上下文


def 拼Cookie(凭据: dict[str, Any]) -> str:
    """把存下来的凭据拼成掌瓦要的 Cookie 字符串。

    字段顺序照第三方实现来的：腾讯的网关按字符串取值，顺序本身不重要，
    但照抄能少一次「我到底漏了哪个」的排查。
    """
    段 = [
        "clientType=9",
        f"uin=o{凭据.get('uin', 0)}",
        f"appid={_APPID}",
        "acctype=qc",
        f"openid={凭据.get('openid', '')}",
        f"access_token={凭据.get('access_token', '') or 'null'}",
        f"userId={凭据.get('userId', '')}",
        "accountType=5",
        f"tid={凭据.get('tid', '')}",
    ]
    return "; ".join(段)


class 掌瓦传输:
    """一次性的请求器。拿到凭据后调用 `取...` 系列。"""

    def __init__(self, 超时: float = 20.0) -> None:
        self._超时 = 超时

    async def 换票(self, openid: str, access_token: str) -> dict[str, Any]:
        """用扫码拿到的 openid + access_token 换掌瓦的 userId / tid。

        换回来的是**完整凭据**：后面查战绩必须带 userId 与 tid，只有
        openid 会被网关判为无效。
        """
        体 = {
            "clienttype": 9,
            "config_params": {"client_dev_name": "23117RK66C", "lang_type": 0},
            "login_info": {
                "appid": _APPID,
                "openid": openid,
                "qq_info_type": 5,
                "sig": access_token,
                "uin": 0,
            },
            "mappid": _MAPPID,
            "mcode": _MCODE,
            "source_game_zone": "agame",
            "game_zone": "agame",
        }
        头 = {
            "Cookie": "clientType=9; openid=null; access_token=null;",
            "User-Agent": _UA,
            "Content-Type": "application/json",
        }
        原始 = await self._请求("POST", _登录换票, headers=头, json体=体, 校验=False)
        数据 = 原始.get("data") or {}
        登录 = 数据.get("login_info") or {}
        return {
            "openid": openid,
            "access_token": access_token,
            "userId": str(登录.get("user_id", "")),
            "tid": str(登录.get("wt", "")),
            "uin": int(登录.get("uin") or 0),
        }

    async def 取主角色(self, 凭据: dict[str, Any]) -> dict[str, Any]:
        """取默认游戏角色（昵称、头像、角色 ID）。"""
        原始 = await self._请求("POST", _主角色, 凭据, json体={"_t": int(time.time())})
        return 原始.get("data") or {}

    async def 取对局列表(
        self,
        凭据: dict[str, Any],
        页游标: str = "",
        每页: int = 20,
    ) -> dict[str, Any]:
        """取近期对局。`页游标` 是上一次返回的 next_baton，空串表示从头。"""
        体 = {"next_baton": 页游标, "page_size": 每页, "_t": int(time.time())}
        原始 = await self._请求("POST", _对局列表, 凭据, json体=体)
        return 原始.get("data") or {}

    async def 取记分板(self, 凭据: dict[str, Any], 对局ID: str) -> dict[str, Any]:
        """取单局的十人记分板：K/D/A、ACS、爆头率、经济、特工。"""
        体 = {"match_id": 对局ID, "_t": int(time.time())}
        原始 = await self._请求("POST", _对局详情, 凭据, json体=体)
        return 原始.get("data") or {}

    async def _请求(
        self,
        方法: str,
        路径: str,
        凭据: dict[str, Any] | None = None,
        *,
        json体: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        校验: bool = True,
    ) -> dict[str, Any]:
        头 = (
            dict(headers)
            if headers
            else {
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Content-Type": "application/json",
                "User-Agent": _UA,
                "Connection": "keep-alive",
                "Cookie": 拼Cookie(凭据 or {}),
            }
        )
        地址 = f"{_接口根}{路径}"
        if _通用查询:
            地址 = f"{地址}?{_通用查询}"

        连接器 = aiohttp.TCPConnector(ssl=_不校验的SSL())
        async with aiohttp.ClientSession(
            connector=连接器, timeout=aiohttp.ClientTimeout(total=self._超时)
        ) as 会话:
            async with 会话.request(方法, 地址, headers=头, json=json体) as 响应:
                文本 = await 响应.text(errors="ignore")
            try:
                原始 = json.loads(文本) if 文本.strip().startswith("{") else {}
            except json.JSONDecodeError:
                raise 业务错误(f"接口没返回 JSON（HTTP {响应.status}）") from None

        if not 校验:
            if 原始.get("result") != 0:
                raise 业务错误(_翻译错误(原始))
            return 原始
        if 原始.get("result") != 0:
            # 登录态过期跟其他错误不是一个性质：前者要用户重新扫码，
            # 后者多半是接口变了。上层用不同类型接。
            raise 登录过期(_翻译错误(原始)) if _是登录问题(原始) else 业务错误(_翻译错误(原始))
        return 原始


def _是登录问题(原始: dict[str, Any]) -> bool:
    码 = 原始.get("result", -1)
    消息 = str(原始.get("errMsg") or 原始.get("msg") or "")
    return 码 in (1001, 1003, 999999) or "ticket" in 消息.lower()


def _翻译错误(原始: dict[str, Any]) -> str:
    """把 result / errMsg 翻成人能读的一句话。

    别把 errMsg 原样抛给用户——那是给抓包的人看的。
    """
    码 = 原始.get("result", -1)
    if _是登录问题(原始):
        return "登录态失效，请重新扫码绑定"
    if 码 == 1018:
        return "查得太快了，稍等一下再试"
    if 码 == 1203:
        return "对方关掉了战绩展示，查不到"
    return f"接口返回错误码 {码}"
