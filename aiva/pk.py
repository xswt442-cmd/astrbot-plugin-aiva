"""PK 的对手解析。

对手身份从消息里捡，按可靠性排：

1. **At 组件的 `qq`** —— 多数平台（OneBot 等）会把 @ 转成组件。
2. 正文里的 `<@!id>` —— 少数平台保留这种写法。
3. **`event.message_obj.raw_message.mentions`** —— QQ 官方平台唯一真正
   拿得到别人 ID 的地方，所以单独抽出来由调用方先查。

## 为什么 QQ 官方必须读 raw_message

QQ 官方适配器（`qqofficial_platform_adapter.py`）里：

```python
bot_mentions = [
    mention for mention in (message.mentions or [])
    if mention.is_you is True and mention.id is not None
]
...
for mention_id in bot_mention_ids:      # 只删 @机器人 的
    plain_content_raw = plain_content_raw.replace(f"<@{mention_id}>", "")
```

平台把**全部** @ 都放在 `message.mentions` 里，但适配器只把 `is_you=True`
的转成 `At` 组件，@别人 的既不进 `msg` 也不留在 `message_str`——QQ 服务端
已经把 content 渲染成 `@昵称` 文本，ID 没了。所以只用组件链和正文正则，
在 QQ 官方平台上**永远认不出对手**（线上实测：用户明明 @ 了人，插件仍报
「没认出要和谁比」，日志里 `message_str` 只剩 `/爱瓦 PK`）。

好在适配器有 `abm.raw_message = message`，整个原始 botpy 消息对象挂在
event 上，`mentions` 就在里面。`botpy` 的 mention 是 `_User`，字段有
`id` / `username` / `bot`，其中 `id` 就是 `member_openid`——和
`event.get_sender_id()` 同一体系，能直接对上凭据文件的键。

拿不到时给用户明确的话，而不是随便挑一个人比——比错人等于泄露别人的战绩。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["找对手", "从提及里找对手", "不是标识的提及"]

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

    QQ 官方平台上这是**唯一**能拿到别人 ID 的入口（见模块 docstring）。
    跳过 `is_you` 的（那是 @机器人）和 `bot` 的。
    """
    排除 = {值 for 值 in (自己, 机器人) if 值}
    for 提及 in getattr(原始消息, "mentions", None) or []:
        if getattr(提及, "is_you", False):
            continue
        if getattr(提及, "bot", False):
            continue
        候选 = _可用(getattr(提及, "id", None), 排除)
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
