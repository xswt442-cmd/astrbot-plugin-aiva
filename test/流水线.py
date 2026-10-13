"""在容器里模拟一次完整流水线，看爱瓦的 handler 到底会不会被调用。

不依赖真实消息：手工造 event，跑 WakingCheckStage 之后的所有阶段。
用法：
    docker exec -w /AstrBot/data/plugins/astrbot_plugin_aiva astrbot python test/流水线.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/AstrBot")
sys.path.insert(0, "/AstrBot/data/plugins/astrbot_plugin_aiva")

from astrbot.core.platform.astrbot_message import (  # noqa: E402
    AstrBotMessage,
    MessageType,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent  # noqa: E402
from astrbot.core.platform.platform_metadata import PlatformMetadata  # noqa: E402


def 造事件(文本: str) -> AstrMessageEvent:
    msg = AstrBotMessage()
    msg.type = MessageType.GROUP_MESSAGE
    return AstrMessageEvent(
        message_str=文本,
        message_obj=msg,
        platform_meta=PlatformMetadata("qq_official", "lg1", "lg1"),
        session_id="ZnNe/2A8FDBA44C38D5B4863B0F49D76E744E",
    )


async def 主() -> None:
    import data.plugins.astrbot_plugin_aiva.main  # noqa: F401

    from astrbot.core.star.star_handler import (
        EventType,
        star_handlers_registry,
    )

    print("注册表里的 handler（全部平台）：")
    hs = star_handlers_registry.get_handlers_by_event_type(
        EventType.AdapterMessageEvent,
        plugins_name=None,
    )
    for h in hs:
        路径 = str(h.handler_module_path)
        if "aiva" in 路径 or "ainong" in 路径:
            print(f"  {路径} :: {h.handler_name}")

    print(f"\n合计 {len(hs)} 个 AdapterMessageEvent handler")

    # 只验证 handler 激活情况，不跑完整 pipeline（需要完整 ctx）
    from astrbot.core.star.filter.command_group import CommandGroupFilter

    event = 造事件("爱瓦 绑定")
    event.is_at_or_wake_command = True
    event.is_wake = True
    激活 = []
    for h in hs:
        通过 = True
        for f in h.event_filters:
            try:
                if not f.filter(event, {}):
                    通过 = False
                    break
            except Exception:  # noqa: BLE001
                通过 = False
                break
        if 通过 and not any(
            isinstance(f, CommandGroupFilter) for f in h.event_filters
        ):
            激活.append(h.handler_name)
    print(f"\n对'爱瓦 绑定' 会激活的 handler：{激活}")


if __name__ == "__main__":
    asyncio.run(主())