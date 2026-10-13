<div align="center">
  <img src="logo.png" alt="爱瓦" width="128">
</div>

# 爱瓦

[![AstrBot](https://img.shields.io/badge/AstrBot-插件-4D7AFF)](https://github.com/AstrBotDevs/AstrBot)
[![QQ](https://img.shields.io/badge/QQ-支持-12B7F5?logo=qq&logoColor=white)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/许可-WTFPL-9CA3AF?logo=open-source-initiative&logoColor=white)](LICENSE)

查无畏契约国服战绩，让模型替你锐评。

AstrBot 插件。扫码绑定自己的掌上无畏契约账号后，问它就能拿到段位与战绩，
由对话模型给出评价。

## 数据来自哪

掌上无畏契约 App（包名 `com.tencent.apps.valorant`）的私有接口
`https://app.mval.qq.com`。

国服**没有**官方公开 API：Riot 官方 API 只覆盖国际服，`api.riotgames.cn`、
`pd.cn.a.pvp.net` 实测 DNS 无记录。所以这条路：

- 必须扫码登录一次（QQ OAuth + 掌瓦换票）；
- `mcode` 是硬编码的渠道串，腾讯轮换即失效；
- 私享战绩开着的号查不到，这个对所有第三方工具都一样。

## 主要功能

- 扫码绑定自己的账号，只有本人能查自己
- `/爱瓦 战绩`：胜负与胜率、场均 K/D/A、KDA、ACS、回合净胜、最近走势、
  地图分布、常用特工
- `/爱瓦 锐评`：先给一句称号，再说打得好／问题／建议
- `/爱瓦 PK <群友昵称>`：和另一个已绑定的人比，模型给趣味分并点评胜负手
- `/爱瓦 开一局`：推演他下一局竞技模式的过程与结果
- 每人一份凭据，互不可见，解绑即删

## 安装

把仓库放进 AstrBot 的 `data/plugins/` 目录，重载插件。AstrBot 会读取
`requirements.txt` 自动装依赖，需要 Python 3.10 以上。

也可以在 AstrBot 面板的插件市场里按仓库地址安装。

## 配置

没有配置项。

## 使用

指令都在 `爱瓦` 指令组下，不占用通用名字。

```
/爱瓦 绑定             QQ 扫码绑定掌上无畏契约账号
/爱瓦 战绩             近期战绩
/爱瓦 锐评             让模型基于近期战绩写一段锐评（带称号）
/爱瓦 PK <群友昵称>    和另一个已绑定的人比一把
/爱瓦 开一局           推演一局竞技模式
/爱瓦 昵称 <名字>      改 PK 时被叫的名字，不带参数看当前值
/爱瓦 状态             看绑定是否正常
/爱瓦 解绑             删除本地凭据
/爱瓦 帮助             列出全部指令
```

也可以直接用自然语言问，模型会调用本插件提供的工具读取提问者自己的战绩。

`/爱瓦 战绩` 给的是：胜负与胜率、场均 K/D/A、KDA、ACS、回合净胜、最近走势、
地图分布、常用特工。掌瓦列表接口没返回的维度（ADR、KAST、经济、命中率分布）
会直接不显示，也不会让模型去编。

登录态通常撑不到一天。过期后**直接发 `/爱瓦 绑定` 重新扫码即可，不用先解绑**。

## 关于 PK

只能和**自己绑过的人**比，且对方那条记录是他本人扫码留下的。

```
/爱瓦 昵称 老王        # 每个人自己起一次
/爱瓦 PK 老王
```

**@ 别人这条路走不通，写昵称就行。** QQ 官方机器人收不到被 @ 的人的标识——
实测 `raw_message.mentions` 是空数组，平台压根没把那个人传下来，适配器里也没有。
所以 PK 只能按名字认人，名字默认取绑定时的平台显示名，可以自己改。

`/爱瓦 昵称` 撞名时会提醒有几个人同名，避免 PK 点到别人。

## 只查自己

插件不提供「查任意人」的入口。原因不只是合规：掌瓦接口拿别人的数据需要
对方的完整登录态，而这个插件只保存本人扫码产生的凭据。

## 已知缺口

- 命中率（头/身/腿）与经济数据只在单局记分板接口里有，要拿到就得对每局
  各发一次请求。当前 `/爱瓦 战绩` 用的是列表接口，**不含这两项**。
- `career/mode/filter` 是 GET 接口，用 POST 打它会拿到 404——那是请求方式
  不匹配，不是端点废弃。本插件不用它。
- 字段名尚未用自己的登录态逐字段核对，见 `docs/CHANGELOG.md` 头一条。

## 开发

```sh
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

改协议相关代码前先跑一次 `uv run python test/verify_mval.py` 探接口还活着没有。

协作约定见 [AGENTS.md](AGENTS.md)，更新日志见 [docs/CHANGELOG.md](docs/CHANGELOG.md)，
术语定义见 [docs/GLOSSARY.md](docs/GLOSSARY.md)，发版流程见
[docs/RELEASING.md](docs/RELEASING.md)。

## License

[WTFPL](LICENSE)。
