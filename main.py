"""爱瓦：无畏契约国服战绩查询。

用户扫码绑定自己的掌上无畏契约账号后，指令与模型都能读到他自己的战绩数据。

数据来自 `app.mval.qq.com`（掌上无畏契约 App 的私有接口）。国服没有官方公开
API：Riot 官方 API 只覆盖国际服，`api.riotgames.cn` 实测 DNS 无记录。所以
这条链路**必须有登录态**，也因此免不了跟着 App 版本走——`mcode` 失效的那天
所有请求会一起报错，文案已经翻译成人话（见 `aiva/transport.py`）。
"""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import command_group, custom_filter
from astrbot.api.star import Context, Star
from astrbot.core.platform.astr_message_event import MessageEventResult
from astrbot.core.star.filter.custom_filter import CustomFilter

# 全部在模块顶层导入。插件加载时就把整个包摸清：少文件、依赖缺失都在启动
# 阶段报错，而不是等用户发了指令才在懒加载里抛模块不存在。
from .aiva.auth.ptlogin import 扫码会话
from .aiva.match import 开局设定, 设定文本
from .aiva.pk import 找对手, 从提及里找对手
from .aiva.prompts import PK提示, 开局提示, 锐评提示
from .aiva.stats import 占优项数, 对比文本, 对比要点, 聚合, 近况文本
from .aiva.storage import (
    凭据仓库,
    凭据摘要,
    凭据是否齐全,
    已绑多久,
    该提醒重绑,
    记绑定时间,
)
from .aiva.transport import (
    业务错误,
    挂日志,
    取对局,
    取段位,
    掌瓦传输,
    登录过期,
)
from .aiva.兜底 import 以组名开头, 取落空参数, 是否落空, 落空提示

_组名 = "爱瓦"

# 组名别名。用户习惯写 `/爱瓦 绑定`，但 QQ 官方适配器在「@机器人 + 指令」
# 这条路径上走的是 At 唤醒分支——`waking_check/stage.py` 的At 分支只置
# `wake_prefix = ""`，**不剥掉 message_str 里的 `/`**（只有 startswith 分支才剥）。
# 于是 message_str 仍是 `/爱瓦 绑定`，组名 `爱瓦` 匹配不上，整条指令静默失败。
# 加一个带斜杠的别名，两种写法都能进。
_组别名 = {f"/{_组名}"}

# 扫码轮询：目标节奏每 2 秒一次，但**按墙钟掐表**，不按次数。
#
# 出码到二维码失效约 60 秒（从出码那一刻起算，不是从第一轮轮询起算）。
# 原来写的是「先 sleep(2) 再发请求」，而服务器到腾讯这一跳实测要 ~3 秒，
# 于是每轮实际占 5 秒，25 轮拉成 125 秒——等问到第 20 轮时腾讯早把码作废了，
# 白白让用户对着废码扫半天。现在改成：记下截止时刻，每轮补足到下一个节奏点，
# 网络慢就从预算里扣，慢到超预算就立刻收工。
_轮询节奏 = 2.0
_轮询预算 = 55.0

# 调模型的最长等待。`tool_loop_agent` 没有内置超时，上游挂起时它就一直等，
# 用户看到的是「机器人死了」，我们连卡在哪一步都不知道。
# 实测正常一次 20~30 秒（max_steps=8，可能多轮工具调用），90 秒留足余量：
# 超了就是上游真有问题，早点失败比让人干等强。
_模型超时 = 90.0

# 直连 provider 时给的系统提示。原来的提示全写在 user 消息里（`prompts.py`
# 生成的 927 字），拆出一层 system 只是为了把「你是谁」和「这次要干什么」
# 分开——省不了多少字，但模型对 system 段的指令遵循明显更稳。
_模型系统提示 = (
    "你在给一个《无畏契约》国服玩家写数据点评。"
    "你只能使用用户消息里给出的统计数字，不要编造任何没给出的数据、"
    "段位、地图或特工。严格按用户要求的格式输出，不要加前言、标题或编号。"
)

_帮助文本 = """爱瓦 · 无畏契约国服战绩查询

数据来自掌上无畏契约 App，需要扫码登录一次。

/爱瓦 绑定
  发起 QQ 扫码登录。扫的是绑定的那个人自己的账号，只有你能查你自己。

/爱瓦 战绩
  近期战绩：胜负与胜率、场均 K/D/A、KDA、ACS、回合净胜、
  最近走势、地图分布、常用特工。

/爱瓦 锐评
  让模型基于上面的数据写一段锐评。会先给一句称号，再分别说打得好、
  问题和一条具体建议。

/爱瓦 开一局
  随机生成一局竞技模式，让模型推演过程与结果。数字是编的，会写明这一点。
  绑定过的话推演贴近你的实际水平，没绑定按中等水平来。

/爱瓦 PK @群友
  和另一个已绑定的人比近期战绩。对方也得自己绑过。
  模型会给两人各打一个趣味分并点评胜负手。

/爱瓦 解绑
  解除绑定并立即删除本地凭据。

/爱瓦 状态
  看当前绑定是否正常。

/爱瓦 帮助
  显示这条消息。"""

_昵称上限 = 16


class 这句给用户(Exception):
    """取不到数据但**不是故障**时抛它，消息原文发给用户。

    跟异常放在一起是因为走返回值得在同一函数里既要 `yield` 又要
    `return <值>`——那在 async generator 里直接 SyntaxError。
    """


class _落空兜底(CustomFilter):
    """`/爱瓦 <不是子命令>` 时自己接住，别让消息流到模型手里。

    `filter` 的返回值语义是「这条消息我管不管」，**不是**「我有没有命中」——
    `CommandGroupFilter.filter` 里`if not self.custom_filter_ok(...): return False`，
    返回 False 会把整个指令组毙掉。所以这里恒返回 True：命中就自己给结果并
    `stop_event()`，没命中就放行给子指令。写成「命中返回 False」会让
    `/爱瓦 绑定` 这种正常指令完全没反应。
    """

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        文本 = getattr(event, "message_str", "") or ""
        # 这条过滤器对**每一条消息**都会跑（CommandGroupFilter 先跑
        # custom_filter_ok 再检查组名），所以第一件事是判断关不关我事。
        if not 以组名开头(文本, _组名):
            return True
        logger.debug(f"[aiva] 指令命中 message_str={文本!r}")
        if 是否落空(文本, _组名):
            event.set_result(
                MessageEventResult().message(落空提示(取落空参数(文本, _组名)))
            )
            event.stop_event()
        return True


class Main(Star):
    # 别写成 `self.爱瓦.add_custom_filter(...)`——`self.爱瓦` 是
    # `RegisteringCommandable`，没有那个方法，加载时会 AttributeError。
    @custom_filter(_落空兜底)
    @command_group(_组名, alias=_组别名)
    def 爱瓦(self):
        """无畏契约国服战绩查询。指令都在这个组下，不占用通用名字。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        """`config` 必须可省。

        AstrBot 的 `star_manager` 只在 `if plugin_config and ...:` 分支里才传配置；
        仓库没有 `_conf_schema.json` 时那个分支不走，于是只传 context。声明成
        必需参数会 `TypeError: missing 1 required positional argument: 'config'`，
        插件整个加载不起来。
        """
        super().__init__(context)
        self.config = config
        # transport 刻意不 import astrbot（本地 pytest 要能直接跑它），
        # 代价是拿不到框架 logger。这里把 logger 挂给它 ——
        # 「用户说没反应」这类问题唯一的出路就是日志。
        挂日志(lambda 一句: logger.info(f"[aiva] {一句}"))
        self._凭据 = 凭据仓库(self._数据目录())

    def _数据目录(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        return Path(get_astrbot_data_path()) / "plugin_data" / "aiva"

    @爱瓦.command("帮助", alias={"help", "菜单"})
    async def 帮助(self, event: AstrMessageEvent):
        """列出所有指令。"""
        yield event.plain_result(_帮助文本)

    @爱瓦.command("绑定")
    async def 绑定(self, event: AstrMessageEvent):
        """QQ 扫码绑定掌上无畏契约账号。"""
        用户 = event.get_sender_id()
        if not 用户:
            yield event.plain_result("拿不到你的用户标识，无法绑定。")
            return

        已有 = self._凭据.读取(用户)
        if 已有 and 凭据是否齐全(已有):
            yield event.plain_result(
                f"你已经绑定了账号（{凭据摘要(已有)}）。要换号先用 /爱瓦 解绑。"
            )
            return

        会话 = 扫码会话()
        try:
            try:
                二维码 = await 会话.出码()
            except RuntimeError as exc:
                logger.warning(f"[aiva] 出码失败：{exc}")
                yield event.plain_result(
                    f"生成二维码失败（{exc}）。腾讯那边可能改了登录页，稍后再试。"
                )
                return
            except Exception as exc:  # noqa: BLE001
                # aiohttp 的连接错、解析错等等一律翻译成人话。
                # 让它冒到框架手上，用户看到的是「在调用插件 astrbot_plugin_aiva
                # 的处理函数 绑定 时出现异常」加一段 traceback——毫无信息量。
                logger.warning(f"[aiva] 出码异常：{type(exc).__name__}: {exc}")
                yield event.plain_result(
                    "生成二维码时网络出错了，稍后再试。（扫不上不是你的问题。）"
                )
                return

            from astrbot.core.message.components import Image, Plain

            yield event.chain_result(
                [
                    Image.fromBytes(二维码),
                    Plain("📱 请用手机 QQ 扫码，50 秒内有效。"),
                ]
            )

            # 从**出码那一刻**起掐表：二维码的寿命是从出码开始算的，
            # 晚一帧问就少一帧可用时间。
            截止 = time.monotonic() + _轮询预算
            下一拍 = time.monotonic()
            问了几轮 = 0
            while True:
                现在 = time.monotonic()
                if 现在 >= 截止:
                    logger.info(f"[aiva] 扫码轮询耗尽预算，共问{问了几轮} 轮")
                    yield event.plain_result(
                        "扫码超时了。二维码只有一分钟有效期，扫完记得点确认。\n"
                        "重新发 /爱瓦 绑定 再试一次。"
                    )
                    return

                # 补足到下一个节奏点。网络慢就从预算里扣，不会像原来那样
                # 把轮询周期越拖越长。
                await asyncio.sleep(max(0.0, 下一拍 - 现在))
                if time.monotonic() >= 截止:
                    logger.info(f"[aiva] 补觉期间预算耗尽，共问{问了几轮} 轮")
                    yield event.plain_result("扫码超时了。重新发 /爱瓦 绑定。")
                    return

                问了几轮 += 1
                下一拍 += _轮询节奏
                try:
                    结果 = await 会话.轮询一次()
                except RuntimeError as exc:
                    logger.info(
                        f"[aiva] 第{问了几轮}轮登录收尾失败：{exc}"
                        f"\n  腾讯原始返回={getattr(会话, '最近原文', '')[:200]!r}"
                        f"\n  跳转链轨迹=\n    "
                        + "\n    ".join(getattr(会话, "跳转轨迹", []) or ["(没走成任何一跳)"])
                    )
                    # 「码过期」和「解析失败」是两回事，用户看到的文案必须分开：
                    # 前者是我们问得太慢，后者是我们自己的解析 bug。
                    if "过期" in str(exc):
                        yield event.plain_result(
                            f"扫码失败：{exc}。\n"
                            "这张码已经在你扫之前就过期了（服务器问腾讯比较慢），"
                            "重新发 /爱瓦 绑定 再试一次。"
                        )
                    else:
                        yield event.plain_result(
                            f"扫码失败：{exc}。\n"
                            "**这不是你的问题**——腾讯已经确认你扫了，是我们没从跳转里"
                            "取到凭据。日志里有轨迹，正在修。"
                        )
                    return
                except asyncio.TimeoutError:
                    # 扫码期间网络抖一下不该把整条指令炸掉——那会在群里弹出
                    # 「在调用插件 astrbot_plugin_aiva 的处理函数 绑定 时出现异常」。
                    # 单次失败按「还没扫完」处理，继续轮询。
                    logger.warning(f"[aiva] 第{问了几轮}轮轮询超时，继续等")
                    continue
                if 结果:
                    logger.info(f"[aiva] 第{问了几轮}轮拿到扫码结果")
                    break
                logger.debug(
                    f"[aiva] 第{问了几轮}轮未确认，腾讯返回 "
                    f"{getattr(会话, '最近原文', '')[:160]!r}"
                )

            传输 = 掌瓦传输()
            try:
                凭据 = await 传输.换票(结果.openid, 结果.access_token)
            except 业务错误 as exc:
                logger.warning(f"[aiva] 换票失败：{exc}")
                yield event.plain_result(f"登录成功但换取接口凭证失败：{exc}")
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[aiva] 换票异常：{type(exc).__name__}: {exc}")
                yield event.plain_result("扫码成功了，但换取接口凭证时网络出错，请重试。")
                return

            if not 凭据是否齐全(凭据):
                yield event.plain_result("登录成功但拿不到完整凭证（缺 userId 或 tid），请重试。")
                return

            self._凭据.写入(用户, 记绑定时间(凭据))
            logger.info(f"[aiva] 用户 {用户} 绑定成功")
            yield event.plain_result(
                f"✅ 绑定成功（{凭据摘要(凭据)}）。\n\n现在可以发 /爱瓦 战绩。"
            )
        finally:
            await 会话.关闭()

    @爱瓦.command("解绑")
    async def 解绑(self, event: AstrMessageEvent):
        """解除绑定并删除本地凭据。"""
        用户 = event.get_sender_id()
        if not self._凭据.删除(用户):
            yield event.plain_result("你还没有绑定。")
            return
        logger.info(f"[aiva] 用户 {用户} 解绑")
        yield event.plain_result("已解绑，本地凭据已删除。")

    @爱瓦.command("状态")
    async def 状态(self, event: AstrMessageEvent):
        """看当前绑定是否正常。"""
        用户 = event.get_sender_id()
        凭据 = self._凭据.读取(用户)
        if not 凭据:
            yield event.plain_result("还没绑定。发 /爱瓦 绑定 扫码登录。")
            return
        if not 凭据是否齐全(凭据):
            yield event.plain_result(
                f"本地记录不完整（{凭据摘要(凭据)}）。请 /爱瓦 解绑 后重新绑定。"
            )
            return

        传输 = 掌瓦传输()
        try:
            角色 = await 传输.取主角色(凭据)
        except 登录过期:
            yield event.plain_result(
                f"⚠️ 已绑定（{凭据摘要(凭据)}），但登录态已失效。"
                "请 /爱瓦 解绑 后重新绑定。"
            )
            return
        except 业务错误 as exc:
            yield event.plain_result(f"已绑定，但接口现在取不到角色信息：{exc}")
            return

        # **状态必须真的打一次战绩接口**。只查主角色是不够的：
        # `get_main_role_raw` 只要 Cookie 形状对就回 result=0，而真正需要
        # 登录态的 `record/list` 早就 1003 了。用户被告知「绑定正常」，
        # 转头发锐评却被告知「登录态失效」——两个都是真话，只是查的不是
        # 同一件事。这是用户实际踩到的问题：状态永远绿着，直到用的时候才炸。
        战绩可用 = True
        战绩原因 = ""
        try:
            await 取对局(凭据, 每页=1)
        except 登录过期:
            战绩可用 = False
            战绩原因 = "登录态已失效"
        except 业务错误 as exc:
            战绩可用 = False
            战绩原因 = f"战绩接口报错：{exc}"
        except Exception as exc:  # noqa: BLE001
            战绩可用 = False
            战绩原因 = f"{type(exc).__name__}: {exc}"

        if not 战绩可用:
            logger.warning(f"[aiva] 用户 {用户} 状态自查失败：{战绩原因}")
            yield event.plain_result(
                f"⚠️ 账号信息还在（{凭据摘要(凭据)}），但**战绩已经取不到了**：\n"
                f"{战绩原因}\n\n"
                "这说明登录态过期了。请 /爱瓦 解绑 后重新绑定。"
            )
            return

        名字 = str(角色.get("nickname") or 角色.get("name") or "").strip()
        行 = f"✅ 绑定正常"
        if 名字:
            行 += f"：{名字}（{凭据摘要(凭据)}）"
        else:
            行 += f"（{凭据摘要(凭据)}）"

        多久 = 已绑多久(凭据)
        if 多久 is not None:
            小时 = 多久 / 3600
            行 += f"\n已绑定 {小时:.1f} 小时"
            if 该提醒重绑(凭据):
                行 += (
                    "\n⚠️ 腾讯的登录态通常撑不满一天。"
                    "如果等下战绩或锐评报「登录态失效」，"
                    "/爱瓦 解绑 后重新绑定即可。"
                )
        else:
            行 += "\n（这份绑定是旧版本存的，没有时间戳）"

        yield event.plain_result(行)

    @爱瓦.command("战绩")
    async def 战绩(self, event: AstrMessageEvent):
        """近期战绩数据。"""
        用户 = event.get_sender_id()
        try:
            数据 = await self._取近期战绩(用户)
        except 这句给用户 as exc:
            yield event.plain_result(str(exc))
            return
        yield event.plain_result(数据[0])

    @爱瓦.command("锐评")
    async def 锐评(self, event: AstrMessageEvent):
        """让模型基于近期数据写一段锐评。"""
        用户 = event.get_sender_id()
        try:
            数据 = await self._取近期战绩(用户)
        except 这句给用户 as exc:
            yield event.plain_result(str(exc))
            return

        文本 = 数据[0]
        try:
            结果 = await self._问模型(event, 锐评提示(文本))
        except Exception as exc:
            logger.warning(f"[aiva] 锐评调用模型失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"调用模型失败：{exc}")
            return
        if not 结果:
            yield event.plain_result(f"模型没给出内容。先把数据给你：\n\n{文本}")
            return
        yield event.plain_result(结果)

    @爱瓦.command("开一局", alias={"开局", "来一局"})
    async def 开一局(self, event: AstrMessageEvent):
        """随机生成一局竞技模式，让模型推演过程与结果。"""
        用户 = event.get_sender_id()
        凭据 = self._凭据.读取(用户)
        摘要: dict[str, Any] | None = None

        if 凭据 and 凭据是否齐全(凭据):
            try:
                原始的对局, _角色 = await 取对局(凭据)
                摘要 = 聚合(原始的对局)
            except Exception as exc:  # noqa: BLE001 - 推演不因查不到就停
                logger.info(f"[aiva] 开一局读战绩失败，按默认水平：{exc}")

        随机源 = random.Random()
        设定 = 开局设定(随机源, 摘要 if 摘要 and 摘要.get("场数") else None)
        try:
            结果 = await self._问模型(event, 开局提示(设定文本(设定)))
        except Exception as exc:
            logger.warning(f"[aiva] 开一局调用模型失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"调用模型失败：{exc}")
            return
        if not 结果:
            yield event.plain_result(f"模型没给出内容。这局的设定：\n\n{设定文本(设定)}")
            return
        yield event.plain_result(结果)

    @爱瓦.command("PK", alias={"pk", "对战"})
    async def PK(self, event: AstrMessageEvent):
        """和另一个已绑定的人比近期战绩。"""
        自己 = event.get_sender_id()
        甲凭据 = self._凭据.读取(自己)
        if not 甲凭据 or not 凭据是否齐全(甲凭据):
            yield event.plain_result("你自己还没绑定。发 /爱瓦 绑定 扫码登录。")
            return

        消息 = getattr(event, "message_obj", None)
        机器人 = str(getattr(event, "self_id", "") or "")

        # QQ 官方平台上组件链和正文都拿不到 @别人 的 ID（适配器只转
        # `is_you` 的），必须回头读 `raw_message.mentions`。详见 aiva/pk.py。
        对手标识 = 从提及里找对手(
            getattr(消息, "raw_message", None),
            自己=自己,
            机器人=机器人,
        )
        if not 对手标识:
            对手标识 = 找对手(
                getattr(消息, "message", None) or [],
                getattr(event, "message_str", "") or "",
                自己=自己,
                机器人=机器人,
            )
        if not 对手标识:
            yield event.plain_result(
                "没认出要和谁比。发「/爱瓦 PK @群友」，@ 到那个人才行——\n"
                "对方也必须自己绑过（绑定只限制本人查自己，插件不会替你去查别人）。"
            )
            return

        乙凭据 = self._凭据.读取(对手标识)
        if not 乙凭据 or not 凭据是否齐全(乙凭据):
            yield event.plain_result("对方还没绑定，比不了。让他自己发 /爱瓦 绑定。")
            return

        甲名 = self._名字(event) or "你"
        乙名 = f"对手{凭据摘要(乙凭据)}"

        try:
            甲列表, 甲角色 = await 取对局(甲凭据)
            乙列表, 乙角色 = await 取对局(乙凭据)
        except 登录过期:
            yield event.plain_result("有人的登录态失效了，请重新 /爱瓦 绑定。")
            return
        except 业务错误 as exc:
            yield event.plain_result(f"接口不给数据：{exc}")
            return
        except Exception as exc:
            logger.warning(f"[aiva] PK 取数据失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"取战绩失败：{exc}")
            return

        甲摘要 = 聚合(甲列表)
        乙摘要 = 聚合(乙列表)
        if not 甲摘要.get("场数") or not 乙摘要.get("场数"):
            yield event.plain_result("两边至少有一个取不到可统计的对局，比不了。")
            return

        要点 = 对比要点(甲摘要, 乙摘要)
        if not 要点:
            yield event.plain_result("两边的数据凑不出可比的项。")
            return

        try:
            结果 = await self._问模型(
                event,
                PK提示(
                    甲名,
                    乙名,
                    对比文本(要点, 甲名, 乙名),
                    占优项数(要点, 甲名, 乙名),
                    近况文本(甲摘要, 取段位(甲角色)),
                    近况文本(乙摘要, 取段位(乙角色)),
                ),
            )
        except Exception as exc:
            logger.warning(f"[aiva] PK 调用模型失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"调用模型失败：{exc}")
            return

        yield event.plain_result(结果 or "模型没有返回内容。")

    async def _名字(self, event: AstrMessageEvent) -> str:
        """发起指令那个人的平台显示名。太长的裁掉，PK 里要念出来。"""
        try:
            名字 = str(event.get_sender_name() or "").strip()
        except Exception:
            return ""
        return 名字[:_昵称上限]

    async def _取近期战绩(self, 用户: str) -> tuple[str, dict[str, Any]]:
        """取数据并折成文本。取不到时抛 `这句给用户`。

        写成 `return None` 是不行的：调用它的指令本身是异步生成器，而这个辅助
        函数也跟着写了 `yield`——在同一函数里既要 `yield` 又要 `return <值>`，
        Python 直接给 SyntaxError（`return with value in async generator`）。
        真正的加载阶段才报错，本地测试看不到。所以这里一律抛，
        调用方负责把话发出去。
        """
        凭据 = self._凭据.读取(用户)
        if not 凭据 or not 凭据是否齐全(凭据):
            raise 这句给用户("还没绑定。发 /爱瓦 绑定 扫码登录。")

        try:
            原始列表, 角色 = await 取对局(凭据)
        except 登录过期 as exc:
            raise 这句给用户("登录态失效了，请重新 /爱瓦 绑定。") from exc
        except 业务错误 as exc:
            raise 这句给用户(f"接口不给数据：{exc}") from exc
        except Exception as exc:
            logger.warning(f"[aiva] 取对局列表失败：{type(exc).__name__}: {exc}")
            raise 这句给用户(f"取战绩失败：{exc}") from exc

        摘要 = 聚合(原始列表)
        if not 摘要.get("场数"):
            raise 这句给用户(
                "接口没返回可统计的对局。可能是这个号还没打过竞技/普通模式，"
                "或者最近的对局被隐私设置挡住了。"
            )
        return 近况文本(摘要, 取段位(角色)), 摘要

    async def _问模型(self, event: AstrMessageEvent, 提示: str) -> str:
        """用当前会话的模型问一句话，返回它写的内容。

        **直连 provider，不走 `tool_loop_agent`。**

        线上实测：走 `tool_loop_agent` 时锐评稳定卡死 90 秒以上，日志里连
        一行上游请求都看不到；而同一个 key、同一个模型直连
        `/chat/completions` 只要 12 秒就回来了。所以问题不在上游、也不在
        提示长度（实测提示 927 字）。

        `tool_loop_agent` 是给「模型要调工具」的场景用的：它会把当前会话
        挂着的**全部**工具 schema 塞进请求（这台机器装了十几个插件，
        bilibili 一个就注册了 3 个 LLM tool），再走 runner 循环。而锐评、
        开局、PK 全都是「拿一段数据换一段文字」，一个工具都不需要。

        两处必须收紧：
        1. 超时。底层是 HTTP，上游挂起时不会自己回来。实测锐评挂过 2 分
           43 秒、日志一行没有——用户只看到「机器人不理人了」。
        2. 重试。agent_runner 配了 `request_max_retries: 5`，叠满轻松超过
           两分钟，所以这里显式压到 1 次。
        """
        try:
            提供方 = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
        except Exception as exc:
            raise RuntimeError(f"取不到当前对话用的模型：{exc}") from exc

        try:
            实例 = await self.context.provider_manager.get_provider_by_id(提供方)
        except Exception as exc:
            raise RuntimeError(f"取不到模型实例 {提供方!r}：{exc}") from exc
        if 实例 is None:
            raise RuntimeError(f"模型 {提供方!r} 不存在或没启用。")

        logger.info(
            f"[aiva] 调模型 provider={提供方!r} 提示{len(提示)}字，"
            f"最多等 {_模型超时}秒"
        )
        起点 = time.monotonic()
        try:
            结果 = await asyncio.wait_for(
                实例.text_chat(
                    prompt=提示,
                    system_prompt=_模型系统提示,
                    request_max_retries=1,
                ),
                timeout=_模型超时,
            )
        except asyncio.TimeoutError:
            用时 = time.monotonic() - 起点
            logger.warning(
                f"[aiva] 调模型超过 {_模型超时}秒（实际{用时:.0f}秒）放弃，"
                f"provider={提供方!r}"
            )
            raise RuntimeError(
                f"模型 {_模型超时}秒没回话（provider={提供方}）。"
                "上游可能挂了，稍后再试。"
            ) from None

        用时 = time.monotonic() - 起点
        文本 = (getattr(结果, "completion_text", "") or "").strip()
        logger.info(f"[aiva] 模型用时{用时:.1f}秒，返回 {len(文本)} 字")
        if not 文本:
            raise RuntimeError(f"模型 {提供方} 返回了空内容，用时{用时:.1f}秒。")
        return 文本
