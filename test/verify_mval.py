"""掌瓦接口的存活探测。

不需要登录也能跑的那部分：确认端点还活着，区分「活着但要登录」和「端点没了」。

区分三件事很重要：

- HTTP 200 + `result:999999` + `auth web ticket fail` = **活着，要登录**。
- HTTP 404 = 这个端点没了。
- 连不上 = 网络或 DNS 的问题。

用法：

    python test/verify_mval.py                          # 探所有要用的端点
    python test/verify_mval.py --只看 /go/agame/career/record/list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import aiohttp

_接口根 = "https://app.mval.qq.com"
_查询 = "source_game_zone=agame&game_zone=agame"

_UA = (
    "mval/2.4.0.10053 Channel/10068 Manufacturer/Xiaomi "
    "Mozilla/5.0 (Linux; Android 14; 23117RK66C Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/101.0.4951.61 Mobile Safari/537.36"
)

# 本插件实际用到的：POST。
_POST端点 = (
    "/go/auth/login_by_qq",
    "/go/account/get_main_role_raw",
    "/go/agame/career/record/list",
    "/go/agame/career/record/scoreboard",
)

# 本插件**不用**、但第三方实现依赖的。留在这里是为了知道它什么时候真的死。
# 注意它是 GET 接口：拿 POST 打会拿到 404，那是请求方式不匹配，不是端点废弃。
_已知未使用 = (("/go/agame/career/mode/filter", "GET"),)

_空凭据Cookie = (
    "clientType=9; uin=o0; appid=102061775; acctype=qc; openid=null; "
    "access_token=null; userId=0; accountType=5; tid=0"
)


async def _探(方法: str, 路径: str) -> tuple[int, str]:
    头 = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/json",
        "User-Agent": _UA,
        "Cookie": _空凭据Cookie,
    }
    timeout是 = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout是) as 会话:
        async with 会话.request(
            方法, f"{_接口根}{路径}?{_查询}", headers=头, json={"_t": 0}
        ) as 响应:
            # 原文回传，只在打印时截断：先截断再 json.loads 会必然失败，
            # 然后被误判成「不是 JSON」。
            return 响应.status, await 响应.text(errors="ignore")


def _判定(状态: int, 文本: str) -> str:
    if 状态 == 404:
        return "❌ 这个请求方式下没有（404）"
    if 状态 != 200:
        return f"⚠️ HTTP {状态}"
    try:
        原始 = json.loads(文本)
    except json.JSONDecodeError:
        return f"⚠️ 不是 JSON（{文本[:60]!r}）"
    码 = 原始.get("result", -1)
    if 码 == 0:
        return "✅ 通了（居然不要登录）"
    if 码 == 999999:
        return "✅ 活着（要求登录，符合预期）"
    return f"✅ 活着（result={码}: {原始.get('errMsg') or 原始.get('msg') or ''}）"


async def 主(只看: str | None = None) -> int:
    检查表 = [路径 for 路径 in _POST端点 if not 只看 or 路径 == 只看] or _POST端点
    失败 = 0
    for 路径 in 检查表:
        try:
            状态, 文本 = await _探("POST", 路径)
        except Exception as exc:  # noqa: BLE001 - 探测脚本要把异常显示出来
            print(f"⚠️ {路径} 连不上：{type(exc).__name__}: {exc}")
            失败 += 1
            continue
        判定 = _判定(状态, 文本)
        print(f"{判定}  POST {路径}")
        if 判定.startswith(("❌", "⚠️")):
            失败 += 1

    if 只看:
        return 1 if 失败 else 0

    for 路径, 方法 in _已知未使用:
        try:
            状态, 文本 = await _探(方法, 路径)
        except Exception as exc:  # noqa: BLE001
            print(f"·  {方法} {路径} 连不上：{type(exc).__name__}")
            continue
        判定 = _判定(状态, 文本)
        print(f"·  {判定}  {方法} {路径}（本插件不用，仅供参考）")

    return 1 if 失败 else 0


if __name__ == "__main__":
    解析 = argparse.ArgumentParser(description="探测掌瓦接口是否还活着")
    解析.add_argument("--只看", help="只探某个路径")
    参数 = 解析.parse_args()
    sys.exit(asyncio.run(主(参数.只看)))
