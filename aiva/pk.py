"""PK 的对手解析。

对手身份从消息里捡，按可靠性排：

1. **`raw_message.msg_elements` / `raw_data`** —— QQ 官方平台的原始报文。
   **这条尚未在线上验证过**（见下面「实测结论」）。
2. `raw_message.mentions` —— botpy 解析出来的 mention 列表。
3. At 组件的 `qq` —— 别的平台（OneBot 等）会把 @ 转成组件。
4. 正文里的 `<@!id>` —— 少数平台保留这种写法。
5. **按昵称匹配** —— 前四条都拿不到时的兜底，由 `main.py` 的 PK 指令接管。

## 实测结论：QQ 官方机器人收不到 @别人

线上日志（2026-10-13 22:28，用户截图里明确 @ 了群友 YJJ）：

```
[aiva] PK 找对手：自己='2A8F...'
  raw_message=PatchedGroupMessage
  mentions=[]            ← 空数组
  组件链=[At, Plain]      ← 只有一个 At，是 @机器人
  message_str='爱瓦 PK'    ← @YJJ 连文本都没留下
```

`mentions` **是空的**。所以不是适配器过滤掉的（适配器只对 `is_you=True`
的做转换，不会让别人凭空消失），而是**平台压根没把被 @ 的人传过来**。

适配器里有 `abm.raw_message = message`，且 `_set_raw_message_fields()` 额外
挂了 `raw_data`（QQ 原始 payload）和 `msg_elements`。@ 元素最可能在这两个
里，所以先试它们；万一都没有，就只能按昵称认人。

**教训**：这条指令最初把 @ 当成唯一入口，失败两次都没日志，只能靠猜字段名。
以后任何「从消息里取 X」的逻辑，取不到时**必须打日志**，这是唯一能收敛
假设的办法——两次白跑都是因为日志里什么都没有。

拿不到时给用户明确的话，而不是随便挑一个人比——比错人等于泄露别人的战绩。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "找对手",
    "从提及里找对手",
    "从原始载荷认对手",
    "提及摘要",
    "不是标识的提及",
]

# `<@1234>` 与 `<@!1234>` 两种写法都存在。长度下限用来滤掉 `<@1>` 这类噪声。
_正文提及 = re.compile(r"<@!?([A-Za-z0-9_-]{6,})>")

# 这些值在 At.qq 里出现过，都不是真实用户。
不是标识的提及 = frozenset({"qq_official", "all", "unknown_selfid"})


def _可用(候选: Any, 排除: set[str]) -> str | None:
    值 = str(候选 or "").strip()
    if not 值 or 值 in 不是标识的提及 or 值 in 排除:
        return None
    return 值


def 从提及里找对手(
    原始消息: Any, *, 自己: str = "", 机器人: str = ""
) -> str | None:
    """从 `raw_message.mentions` 里找对手，找不到返回 None。

    跳过 `is_you` 的（那是 @机器人）和 `bot` 的。

    注意：QQ 官方平台上实测这个数组是**空的**（见模块 docstring），所以
    别把它当唯一入口。
    """
    排除 = {值 for 值 in (自己, 机器人) if 值}
    for 提及 in getattr(原始消息, "mentions", None) or []:
        if getattr(提及, "is_you", False):
            continue
        if getattr(提及, "bot", False):
            continue
        候选 = _可用(_标识(提及), 排除)
        if 候选:
            return 候选
    return None


def _标识(项: Any) -> str:
    """从一个 mention 对象里取用户标识。

    `botpy` 的 mention 有 `id` / `member_openid` / `user_openid` 三个可能的
    字段，谁有值取谁——`member_openid` 才是群里的用户标识，也正是
    `get_sender_id()` 返回的那个。
    """
    for 名 in ("member_openid", "id", "user_openid"):
        值 = str(getattr(项, 名, "") or "").strip()
        if 值:
            return 值
    return ""


def 提及摘要(原始消息: Any) -> list[dict[str, Any]]:
    """把 mentions / msg_elements 压成可读的摘要，给日志用。"""
    出 = []
    for 提及 in getattr(原始消息, "mentions", None) or []:
        出.append(
            {
                "member_openid": getattr(提及, "member_openid", None),
                "id": getattr(提及, "id", None),
                "username": getattr(提及, "username", None),
                "is_you": getattr(提及, "is_you", None),
                "bot": getattr(提及, "bot", None),
            }
        )
    return 出


def 从原始载荷认对手(
    原始消息: Any, *, 自己: str = "", 机器人: str = ""
) -> str | None:
    """从 QQ 原始 payload（`raw_data` / `msg_elements`）里找被 @ 的人。

    这是 QQ 官方平台上最有可能拿到对手的地方：`mentions` 实测为空，
    但适配器 `_set_raw_message_fields` 把 QQ 的原始报文留在了
    `raw_message.raw_data` 和 `msg_elements` 上。

    认得的形态全试一遍，认不出就返回 None（别猜）：
    - `msg_elements` 里 `element_type == "mention"` 的 `user_id` /
      `member_openid` / `qq`；
    - `raw_data` 里 `mentions` / `at_users` 之类数组的 `member_openid`。
    """
    排除 = {值 for 值 in (自己, 机器人) if 值}

    for 元素 in getattr(原始消息, "msg_elements", None) or []:
        if not isinstance(元素, dict):
            continue
        if str(元素.get("element_type") or "").lower() != "mention":
            continue
        # mention 元素的 user_id 可能是 QQ 号，也可能是 openid
        for 名 in ("member_openid", "user_id", "id", "qq", "user_openid"):
            候选 = _可用(元素.get(名), 排除)
            if 候选:
                return 候选

    载荷 = getattr(原始消息, "raw_data", None)
    if isinstance(载荷, dict):
        for 名 in ("mentions", "at_users", "mention_list", "at_list"):
            数组 = 载荷.get(名)
            if not isinstance(数组, list):
                continue
            for 项 in 数组:
                if isinstance(项, dict):
                    候选 = _可用(
                        项.get("member_openid")
                        or 项.get("id")
                        or 项.get("user_id")
                        or 项.get("user_openid"),
                        排除,
                    )
                else:
                    候选 = _可用(项, 排除)
                if 候选:
                    return 候选
    return None


def 找对手(
    消息列表, 文本: str, *, 自己: str = "", 机器人: str = ""
) -> str | None:
    """从组件链和正文里找 PK 的对手标识，找不到返回 None。

    `自己` 与 `机器人` 都得排掉：群里 @机器人 同样会生成一个 At 组件，
    不排掉的话「@机器人 PK @小明」会把机器人当成 PK 对象。
    """
    排除 = {值 for 值 in (自己, 机器人) if 值}

    for 组件 in 消息列表 or []:
        候选 = _可用(getattr(组件, "qq", None), 排除)
        if 候选:
            return 候选

    for 命中 in _正文提及.finditer(文本 or ""):
        候选 = _可用(命中.group(1), 排除)
        if 候选:
            return 候选

    return None
