# Agent guide

`aiva` 是 AstrBot 插件，通过掌上无畏契约（掌瓦）App 的私有接口读取
《无畏契约》国服战绩，交给模型做锐评。

## 约定

- 包内一律用相对导入。插件目录被 AstrBot 当成包加载，顶层包名在容器里
  import 不到。
- 指令全在 `爱瓦` 指令组下（`/爱瓦 战绩`），不占用通用名字。改动指令时
  帮助文本里的示例要一起改。
- `requirements.txt` **手写**，理由与检查项见 `docs/RELEASING.md`。
- 网络请求只用 `aiohttp`。
- 持久化数据放 AstrBot 的 `data/plugin_data/aiva/`，不放插件目录。
- 凭据不写日志、不进异常消息、不进提交。解绑时删文件，不保留。
  `aiva/storage.py` 里的 `凭据摘要` 是给日志用的裁剪版，
  `扫码结果.__repr__` 也不带本体。
- 地图名与特工名的中文表取自 Riot 自己的 `valorant-api.com`
  （`/v1/maps`、`/v1/agents`，带 `?language=zh-CN`）。
  **不许凭记忆改**：凭记忆写过一次，四个是错的、一个是编的。
- 掌瓦能返回 `used_map.name` 与 `hero_name` 的本地化名字，
  有真实数据时优先用接口给的，常量表只在没有历史数据时兜底。

## 数据边界（写提示词时必须知道）

掌瓦对局列表 **没有** ADR、KAST、经济、攻防回合、命中率分布、武器明细、队友信息。
`aiva/prompts.py` 里的 `字段白名单` 把这份清单写进提示词，
这是为了让模型不去套 CS2 那套指标编答案——爱完美踩过这个坑，
模型输出与数据源严重脱轨。

同理，接口返回三部曲之后若要新增维度，**先改 `stats.py` 拿到真实字段**，
不要先在提示词里许给模型。

## config 为什么必须可省

AstrBot 的 `star_manager` 这样注入配置：

```python
if plugin_config and metadata.star_cls_type:
    star = metadata.star_cls_type(context=context, config=plugin_config)
else:
    star = metadata.star_cls_type(context=context)
```

仓库没有 `_conf_schema.json` 时第一个分支不走，于是只传 `context`。
`__init__` 里把 `config` 声明成必需参数会直接 `TypeError`，插件整个加载不起来。

## 登录链路的三条实测结论

写 `aiva/auth/ptlogin.py` 之前摸出来的，改这个文件前先过一遍：

1. 出码必须打 `xui.ptlogin2.qq.com/ssl/ptqrshow`。换成 `ssl.ptlogin2.qq.com`
   会返回一段 HTML 而不是 PNG——同一路径，只有 `xui.` 子域出图。
2. `xlogin` 下发的 `pt_login_sig` 要用**同一个 cookie jar** 带回去。
   重开 Session 会丢，轮询必然失败。所以 `扫码会话` 是长命对象，
   用完必须 `await 关闭()`。
3. 掌瓦这条链路**纯 HTTP，不需要浏览器侧车**（与爱农的营地链路不同，
   那边要 YSDK 签名）。

## 接口会失效

`app.mval.qq.com` 是私有接口，`mcode` 硬编码。腾讯轮换的那天所有请求会
一起失败，表现是 `业务错误`：接口返回错误码 N。
到时候要重新抓包，而不是继续调提示词。

`career/mode/filter` 是 **GET** 接口。用 POST 打它会得到 404，
而这只是请求方式不匹配——换成 GET 就正常返回 999999（活着，要登录）。
（这条结论纠正过一次：最初把 POST 的 404 当成端点废弃写进了文档，是错的。）

本插件第一次改动/发布前先跑 `test/verify_mval.py` 探一遍；
改 `aiva/stats.py` 的字段映射前，用真实登录态跑一次并核对字段名。
