"""QQ 扫码登录，拿到掌瓦要的 openid 与 access_token。

掌瓦这条链路比营地简单：全流程纯 HTTP，**不需要浏览器侧车**，也不需要
XXTEA / YSDK 签名。唯一的「签名」是轮询时的 `ptqrtoken`，纯算术。

实测记录（2026-10-13，协议日期要写进注释而不是靠记忆）：

- 出码必须打 `https://xui.ptlogin2.qq.com/ssl/ptqrshow`。换成 `ssl.ptlogin2.qq.com`
  域名会返回一段 HTML 而不是 PNG——同一个 `/ssl/` 路径，只有放在 `xui.` 子域下才出图。
- `xlogin` 会下发 `pt_login_sig`、`pt_clientip`、`pt_serverip` 等 Cookie。后续请求
  必须用**同一个 cookie jar**，重开 Session 会丢 `pt_login_sig`，轮询必然失败。
- 不带 cookie 打业务接口时，服务端返回 `result:999999` +
  `errMsg:"auth web ticket fail ... DecodeTgpTicket"`，这是「活着但要登录」的
  标准答案，不要当成接口挂了。
"""

from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any

import aiohttp

__all__ = ["扫码会话", "扫码结果", "还没轮到"]

# 手机 QQ 扫码不可逆着来：这组参数是 QQ 互联的移动侧参数，换成别的 unionid
# 会拿到一个能被后续接口拒掉的 token。
_XLOGIN = (
    "https://xui.ptlogin2.qq.com/cgi-bin/xlogin?"
    "pt_enable_pwd=1&appid=716027609&pt_3rd_aid=102061775&daid=381"
    "&pt_skey_valid=0&style=35&force_qr=1&autorefresh=1"
    "&s_url=http%3A%2F%2Fconnect.qq.com&refer_cgi=m_authorize"
    "&ucheck=1&fall_to_wv=1&status_os=12"
    "&redirect_uri=auth%3A%2F%2Ftauth.qq.com%2F"
    "&client_id=102061775&pf=openmobile_android&response_type=token"
    "&scope=all&sdkp=a&sdkv=3.5.17.lite"
    "&sign=a6479455d3e49b597350f13f776a6288"
    "&status_machine=MjMxMTdSSzY2Qw%3D%3D&switch=1"
    "&time=1763280194&show_download_ui=true"
    "&h5sig=trobryxo8IPM0GaSQH12mowKG-CY65brFzkK7_-9EW4"
    "&loginty=6"
)
_出码地址 = "https://xui.ptlogin2.qq.com/ssl/ptqrshow"
_轮询地址 = "https://xui.ptlogin2.qq.com/ssl/ptqrlogin"
_APPID = "716027609"
_DAID = "381"
_第三方AID = "102061775"

# 跳转链每一跳单独给 5 秒。会话的 total=20 是单条请求预算，而 _追跳转 最多走
# 5 跳，沿用值得100 秒——用户在群里发一句话就能把sock_connect 打断。
_跳转超时 = 5.0

_UA = (
    "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/101.0.4951.61 Mobile Safari/537.36"
)
_通用头 = {
    "User-Agent": _UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "X-Requested-With": "com.tencent.apps.valorant",
    "Referer": "https://openmobile.qq.com/",
}


# 轮询一次拿不到结果时抛这个，调用方继续下一个周期。
class 还没轮到(Exception):
    pass


class 扫码结果:
    """一次成功扫码拿到的东西。够换掌瓦凭证就行，多一样都不存。"""

    __slots__ = ("openid", "access_token")

    def __init__(self, openid: str, access_token: str) -> None:
        self.openid = openid
        self.access_token = access_token

    def __repr__(self) -> str:  # pragma: no cover - 只在调试日志里出现
        # 凭据本体不进 repr。绑定失败时日志里常见 repr，别在这里漏。
        return f"扫码结果(openid长度={len(self.openid)})"


def 算二维码令牌(qrsig: str) -> int:
    """QQ 那个 hash33：e = (e * 33 + ord(c)) & 0x7FFFFFFF。

    不是加密，是他 JS 里的一段累加。写在这里免得后人以为要引 crypto 库。
    """
    累加 = 0
    for 字符 in qrsig:
        累加 = (累加 * 33 + ord(字符)) & 0x7FFFFFFF
    return 累加


class 扫码会话:
    """一次扫码的完整生命周期：出码 → 轮询 → 抽 openid。

    用完必须 `await 关闭()`，cookie jar 里装着 `pt_login_sig` 与用户的扫码态。
    """

    def __init__(self) -> None:
        self._会话: aiohttp.ClientSession | None = None
        self._qrsig = ""
        self._登录_sig = ""
        self._jsver = "28d22679"
        self._aegis = ""
        # 最近一次轮询拿回来的腾讯原始响应，只给调用方看（打日志 / 排查）。
        self.最近原文 = ""
        # 跳转链的逐跳轨迹（URL / 状态 / 下一跳 / 正文摘要）。
        # 只给调用方看：这个模块刻意不 import astrbot，好让本地 pytest 能跑。
        self.跳转轨迹: list[str] = []

    async def 出码(self) -> bytes:
        """取一张二维码 PNG，同时把会话内部状态准备好。

        抛 `RuntimeError` 表示腾讯侧没给图，直接让用户重试，不要往下走。
        """
        if self._会话 is None:
            # 腾讯这套跳转会在多个子域之间来回，jar 默认的严格策略会把
            # 回来的 Cookie 丢掉，pt_login_sig 就断了。
            self._会话 = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                timeout=aiohttp.ClientTimeout(total=20),
            )
        assert self._会话 is not None

        头 = {**_通用头, "Cookie": "accountType=5; clientType=9", "Accept": "text/html,*/*"}
        async with self._会话.get(_XLOGIN, headers=头) as 响应:
            页面 = await 响应.text(errors="ignore")

        self._登录_sig = self._取cookie("pt_login_sig")
        self._aegis = self._取cookie("__aegis_uid")
        m = re.search(r"/monorepo/([0-9A-Za-z]+)/ptlogin/js/", 页面)
        if m:
            self._jsver = m.group(1)

        参数 = urllib.parse.urlencode(
            {
                "s": "8",
                "e": "0",
                "appid": _APPID,
                "type": "0",
                "t": str(time.time()),
                "u1": "http://connect.qq.com",
                "daid": _DAID,
                "pt_3rd_aid": _第三方AID,
            }
        )
        async with self._会话.get(
            f"{_出码地址}?{参数}",
            headers={**_通用头, "Referer": _XLOGIN, "Accept": "image/webp,image/*,*/*;q=0.8"},
        ) as 响应:
            图片 = await 响应.read()

        if 图片[:8] != b"\x89PNG\r\n\x1a\n":
            # 服务端给了一张 HTML（多半是风控页或被跳走了）。这时候继续轮询
            # 只会拿到一串无意义的 code，不如早点失败。
            raise RuntimeError(f"出码没拿到 PNG（{len(图片)} 字节）")

        self._qrsig = self._取cookie("qrsig")
        if not self._qrsig:
            raise RuntimeError("出码了但没拿到 qrsig")
        return 图片

    async def 轮询一次(self) -> 扫码结果 | None:
        """探一次。返回 None 表示还没扫，调用方再等一轮。

        抛 `RuntimeError` 表示这次扫码已经废了（超时/过期），要重新出码。
        """
        if self._会话 is None or not self._qrsig:
            raise RuntimeError("还没出码就轮询")

        参数 = {
            "u1": "http://connect.qq.com",
            "from_ui": "1",
            "type": "1",
            "ptlang": "2052",
            "ptqrtoken": str(算二维码令牌(self._qrsig)),
            "daid": _DAID,
            "aid": _APPID,
            "pt_3rd_aid": _第三方AID,
            "pt_uistyle": "35",
            "jsver": self._jsver,
            "r": str(time.time()),
            "device": "2",
            "ptopt": "1",
        }
        if self._登录_sig:
            参数["login_sig"] = self._登录_sig
        if self._aegis:
            参数["aegis_uid"] = self._aegis

        async with self._会话.get(
            _轮询地址,
            params=参数,
            headers={
                **_通用头,
                "User-Agent": f"{_UA} tencent_game_emulator",
                "Referer": _XLOGIN,
                "Accept": "*/*",
            },
        ) as 响应:
            文本 = await 响应.text(errors="ignore")

        # 原样留一份给调用方打日志。这个模块刻意不 import astrbot
        # （本地 pytest 要能直接跑），所以日志由 main.py 负责。
        self.最近原文 = 文本
        return await self._拆回调(文本)

    async def _拆回调(self, 文本: str) -> 扫码结果 | None:
        """把 ptuiCB(...) 里的一段话拆成登录结果。"""
        m = re.search(r"ptuiCB\('([^']*)','([^']*)','([^']*)','([^']*)','([^']*)'", 文本)
        if not m:
            return None
        码 = m.group(1)
        if 码 in ("65",):  # 二维码失效
            raise RuntimeError("二维码已失效")
        if 码 in ("66", "67"):  # 未失效/等待扫码，都不是结果
            return None
        if 码 != "0":
            return None

        跳转 = m.group(3).replace("\\/", "/").replace("\\x26", "&")
        凭据 = await self._追跳转(跳转)
        if 凭据 and 凭据.openid and 凭据.access_token:
            return 凭据
        # code=0 表示腾讯那边判定「扫了并确认了」，但我们没从跳转链里捞到
        # openid/access_token。这是**我们**的解析问题，不是用户没扫——
        # 必须跟「还没扫」区分开，否则用户只会看到一句「超时了」。
        raise RuntimeError("腾讯已确认扫码，但没取到 openid/access_token")

    async def _追跳转(self, 地址: str, 最多: int = 12) -> 扫码结果 | None:
        """跟着跳转链走，从 auth:// 回调里捞出 openid 与 access_token。

        每一跳都套自己的短超时：会话的 `total=20` 是**整条请求**的预算，
        而这里要走的跳数不少，用会话默认值最坏能拖到一百多秒——用户在群里
        发一句话就能把 `sock_connect` 打断，冒出来的 `asyncio.TimeoutError`
        会一路穿透到 handler，把整条指令炸成「调用插件时出现异常」。

        腾讯这套登录链的形状不固定，实测见过三种「跳到下一跳」的方式：

        1. HTTP 302，用响应头 `Location`；
        2. 正文里的 ``location.href="..."`` / ``location.replace("...")``；
        3. ``<meta http-equiv="refresh" content="0;url=...">``。

        只认第1 种会在这里直接断链——`check_sig` 就是返回第 2 种的。
        每跳都记进 `self.跳转轨迹`，出问题时能直接看清卡在哪。
        """
        if self._会话 is None:
            return None
        self.跳转轨迹 = []
        当前 = 地址
        已走过: set[str] = set()
        for _ in range(最多):
            if not 当前 or 当前 in 已走过:
                break
            已走过.add(当前)
            凭据 = _从地址提凭据(当前)
            if 凭据:
                self._记轨迹(f"第{len(self.跳转轨迹) + 1}跳 地址里直接有凭据")
                return 凭据
            if 当前.startswith("auth://"):
                break
            正文 = ""
            下一位 = ""
            try:
                async with self._会话.get(
                    当前,
                    allow_redirects=False,
                    headers={**_通用头, "Referer": _XLOGIN, "Accept": "*/*"},
                    timeout=aiohttp.ClientTimeout(total=_跳转超时),
                ) as 响应:
                    状态 = 响应.status
                    正文 = await 响应.text(errors="ignore")
                    下一位 = (响应.headers.get("Location", "") or "").strip()
            except (TimeoutError, aiohttp.ClientError, OSError) as exc:
                # 单跳失败不是登录失败，继续试下一跳
                self._记轨迹(
                    f"{_短(当前)} -> 网络异常 {type(exc).__name__}: {exc}"
                )
                break

            if not 下一位:
                # 没有 302。那就看看正文里是用 JS 还是 meta 指向下一跳。
                下一位 = _正文里的下一跳(正文)
            self._记轨迹(
                f"{_短(当前)} -> {状态} {_短(下一位) if 下一位 else '(无下一跳)'} "
                f"正文{len(正文)}字 {_短(正文, 120)!r}"
            )

            if 下一位:
                当前 = 下一位
                continue
            m = re.search(r"(auth://tauth\.qq\.com/[^\s\"'<>]+)", 正文.replace("\\/", "/"))
            if m:
                凭据 = _从地址提凭据(m.group(1))
                if 凭据:
                    return 凭据
            凭据 = _从地址提凭据(正文)
            if 凭据:
                return 凭据
            break
        return None

    def _记轨迹(self, 一句: str) -> None:
        """记一跳。轨迹要留着给调用方打日志，登录态相关的值不能进日志。"""
        self.跳转轨迹.append(一句)

    def _取cookie(self, 名字: str) -> str:
        if self._会话 is None:
            return ""
        for cookie in self._会话.cookie_jar:
            if cookie.key == 名字:
                return cookie.value or ""
        return ""

    async def 关闭(self) -> None:
        if self._会话 is not None:
            await self._会话.close()
            self._会话 = None


def _正文里的下一跳(正文: str) -> str:
    """从一段正文里找出「下一跳该去哪」。

    腾讯的 `check_sig` 之类接口不返回 302，而是在正文里用 JS 指向下一跳。
    常见三种，按可靠性排序：

    1. ``location.href = "..."`` / ``location.replace("...")`` / ``location.assign``
    2. ``<meta http-equiv="refresh" content="0;url=...">``
    3. ``window.location = "..."``

    正文里的 ``\\x26`` 是被转义过的 ``&``，``\\/`` 是转义过的 ``/``，
    不还原的话拼出来的 URL 会少参数。
    """
    if not 正文:
        return ""
    还原 = 正文.replace("\\/", "/").replace("\\x26", "&").replace("\\u0026", "&")

    # 排除明显不是「下一跳」的：about:blank、javascript:、data:、纯锚点。
    模式 = (
        r"""(?:window\.)?location(?:\.href)?\s*(?:=|\.replace\(|\.assign\()\s*"""
        r"""["']([^"']+)["']"""
        r"""|http-equiv=["']?refresh["']?[^>]*?content=["'][^"']*?url=([^"']+)["']"""
        r"""|window\.location\s*=\s*["']([^"']+)["']"""
    )
    m = re.search(模式, 还原, re.IGNORECASE)
    if not m:
        return ""
    候选 = next((g for g in m.groups() if g), "")
    候选 = 候选.strip()
    if not 候选 or 候选.startswith(("about:", "javascript:", "data:", "#")):
        return ""
    return 候选


def _短(文本: str, 长度: int = 80) -> str:
    """把 URL 或正文压短，便于进日志。"""
    s = (文本 or "").replace("\n", " ").replace("\r", " ")
    return s if len(s) <= 长度 else f"{s[:长度]}…"


def _从地址提凭据(文本: str) -> 扫码结果 | None:
    """从 auth:// 回调（或含它的一段正文）里取 openid 与 access_token。

    回调格式是 `auth://tauth.qq.com/?#access_token=...&openid=...`，
    注意 `#` 在 query 前头，直接用 urlparse.query 拿不到，要把 `#` 换成 `&`。
    """
    if not 文本:
        return None
    取 = 文本
    for 转义 in ("\\/", "\\x26", "\\u0026"):
        取 = 取.replace(转义, "/" if 转义 == "\\/" else "&")
    if "#" in 取:
        取 = 取.replace("#", "&", 1)
    m = re.search(r"(auth://[^\s\"'<>]+)", 取)
    查询 = m.group(1) if m else 取
    if "?" in 查询:
        查询 = 查询.split("?", 1)[1]
    字段: dict[str, str] = {}
    try:
        from urllib.parse import parse_qs

        for 键, 值 in parse_qs(查询, keep_blank_values=True).items():
            if 值:
                字段[键] = 值[0]
    except Exception:  # noqa: BLE001 - 格式不是 query 就没东西可取，返回 None 即可
        return None
    openid = (字段.get("openid") or "").strip()
    token = (字段.get("access_token") or "").strip()
    if not openid or not token:
        return None
    return 扫码结果(openid, token)


def 装进凭据库(登录: 扫码结果) -> dict[str, Any]:
    """把扫码结果转成存库用的字典（去掉 openid 之外的所有东西）。"""
    # 只留这两样。上面一层已经有 json 序列化，这里不必再处理。
    return {"openid": 登录.openid, "access_token": 登录.access_token}


def 短化(v: Any, 长度: int = 8) -> str:
    """把凭据裁一小段给人看。日志里判断「有没有」用够了，本体不该出现在日志。"""
    s = str(v)
    return f"{s[:长度]}…（共{len(s)}位）" if len(s) > 长度 else "（空）"
