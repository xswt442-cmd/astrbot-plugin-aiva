"""PK 的对手解析。

对手身份从消息里捡，按可靠性排：

1. `At` 组件 —— 多数平台会把 @ 转成组件，`qq` 就是用户标识。
2. 正文里的 `<@!id>` —— QQ 官方适配器只把「@机器人」转成组件，@别人
   会原样留在正文里，只能从文本里抠。

QQ 官方平台上这两处都常常拿不到别人：适配器只把「@机器人」转成组件，
而被 @ 的人留在平台 `mentions` 里适配器根本不读。所以拿不到时给用户明确的
话，而不是随便挑一个人比——比错人等于泄露别人的战绩概览。
"""

from __future__ import annotations

import re

__all__ = ["找对手", "不是标识的提及"]

# `<@1234>` 与 `<@!1234>` 两种写法都存在。长度下限用来滤掉 `<@1>` 这类噪声。
_正文提及 = re.compile(r"<@!?([A-Za-z0-9_-]{6,})>")

# 这些值在 At.qq 里出现过，都不是真实用户。
不是标识的提及 = frozenset({"qq_official", "all", "unknown_selfid"})


def _可用(候选: str, 排除: set[str]) -> bool:
    return bool(候选) and 候选 not in 不是标识的提及 and 候选 not in 排除


def 找对手(消息列表, 文本: str, *, 自己: str = "", 机器人: str = "") -> str | None:
    """从消息里找出 PK 的对手标识，找不到返回 None。

    `自己` 与 `机器人` 都得排掉：群里 @机器人 同样会生成一个 At 组件，
    不排掉的话「@机器人 PK @小明」会把机器人当成 PK 对象。
    """
    排除 = {值 for 值 in (自己, 机器人) if 值}

    for 组件 in 消息列表 or []:
        候选 = getattr(组件, "qq", None)
        if 候选 is None:
            continue
        候选 = str(候选)
        if _可用(候选, 排除):
            return 候选

    for 命中 in _正文提及.finditer(文本 or ""):
        候选 = 命中.group(1)
        if _可用(候选, 排除):
            return 候选

    return None
