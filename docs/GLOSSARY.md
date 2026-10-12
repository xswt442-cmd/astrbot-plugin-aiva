# 术语

**掌瓦** — 「掌上无畏契约」，腾讯官方的《无畏契约》国服 App，包名
`com.tencent.apps.valorant`。国服战绩数据只有它的私有接口能给：
Riot 官方 API 只覆盖国际服，`api.riotgames.cn`、`pd.cn.a.pvp.net`
实测 DNS 无记录。

**mcode** — 掌瓦请求里的渠道串，硬编码。腾讯轮换的那天所有请求会一起失败。
这不是签名，也没有加密，就是一个渠道标识。

**mval** — `app.mval.qq.com`，掌瓦的 API 域名。所有数据接口都在这里。

**openid / access_token / userId / tid** — 登录态四件套。扫码只拿到前两样，
要再调 `login_by_qq` 换出 `userId` 与 `tid` 才能查战绩——只有 openid
会被网关判为无效。

**ptqrtoken** — 轮询二维码状态时用的一个数，`e = (e * 33 + ord(c)) & 0x7FFFFFFF`。
不是加密，是他 JS 里的一段累加（hash33）。

**ACS** — Average Combat Score，场均战斗评分。掌瓦的 `score_avg`。
`score` 是整局累计的战斗分，两者差一个回合数。ACS 是无畏契约里最接近
「这一局打得怎么样」的单个数，但它**不等于**强弱的全部。

**KDA 字符串** — 掌瓦把击杀/死亡/助攻塞在一个字符串里，形如 `"13/18/10"`。
不是三个整数，要自己拆。

**result_title** — 胜负，值是中文的 `"获胜"` / `"失败"` / `"平局"`。
按首字母判断会全部判错。

**特工（agent）** — 角色。四个定位：决斗、先锋、控场、哨卫。
中文名取 Riot 官方（`valorant-api.com` 的 `@language=zh-CN`），不要自己译。

**地图名** — 同样用接口返回的 `used_map.name`（已本地化）。
`aiva/match.py` 里的常量表只在没有历史数据时兜底，那份名单取自
`valorant-api.com`，不是凭记忆写的。

**加时（OT）** — 竞技模式 12:12 之后进入，需净胜 2 回合。先到 14 才算赢。
