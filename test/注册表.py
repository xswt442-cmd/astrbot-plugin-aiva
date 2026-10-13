"""打印运行中 AstrBot 里 aiva 的 handler 注册情况与 filter 链。

用法（容器内）：
    cd /AstrBot/data/plugins/astrbot_plugin_aiva && python test/注册表.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/AstrBot")
sys.path.insert(0, "/AstrBot/data/plugins/astrbot_plugin_aiva")

from astrbot.core.star.filter.command import CommandFilter  # noqa: E402
from astrbot.core.star.filter.command_group import (  # noqa: E402
    CommandGroupFilter,
)
from astrbot.core.star.star_handler import (  # noqa: E402
    EventType,
    star_handlers_registry,
)

import data.plugins.astrbot_plugin_aiva.main as 插件  # noqa: E402,F401


def 造(文本: str):
    from astrbot.core.platform.astrbot_message import (
        AstrBotMessage,
        MessageType,
    )
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.platform_metadata import PlatformMetadata

    msg = AstrBotMessage()
    msg.type = MessageType.GROUP_MESSAGE
    e = AstrMessageEvent(
        message_str=文本,
        message_obj=msg,
        platform_meta=PlatformMetadata("qq_official", "lg1", "lg1"),
        session_id="s",
    )
    e.is_at_or_wake_command = True
    e.is_wake = True
    return e


def 报告() -> None:
    handlers = star_handlers_registry.get_handlers_by_event_type(
        EventType.AdapterMessageEvent,
        plugins_name=None,
    )
    print(f"总 handler 数：{len(handlers)}")

    本插件 = []
    for h in handlers:
        if "aiva" in str(h.handler_module_path):
            本插件.append(h)
            是组 = any(isinstance(f, CommandGroupFilter) for f in h.event_filters)
            print(f"\n== {h.handler_name}  是组handler={是组}")
            print(f"   extras_configs={getattr(h, 'extras_configs', None)}")
            for f in h.event_filters:
                if isinstance(f, CommandGroupFilter):
                    print(f"   - Group 完整名={f.get_complete_command_names()}")
                    for s in f.sub_command_filters:
                        print(
                            f"       └ {s.command_name!r} 完整名={s.get_complete_command_names()}"
                        )
                elif isinstance(f, CommandFilter):
                    print(f"   - Cmd {f.command_name!r} 完整名={f.get_complete_command_names()}")
                else:
                    print(f"   - {type(f).__name__}")

    print("\n\n===== 模拟 waking_check：对 '爱瓦 绑定' 逐 handler 试filter =====")
    event = 造("爱瓦 绑定")
    for h in 本插件:
        通过 = True
        细节 = []
        for f in h.event_filters:
            try:
                r = f.filter(event, {})
            except Exception as e:  # noqa: BLE001
                细节.append(f"{type(f).__name__}=EXC({e})")
                通过 = False
                break
            细节.append(f"{type(f).__name__}={r}")
            if not r:
                通过 = False
                break
        print(f"  {'✅' if 通过 else '— '} {h.handler_name}: {细节}")

    print("\n===== 若某handler 通过，parsed_params =====")
    event2 = 造("爱瓦 绑定")
    for h in 本插件:
        for f in h.event_filters:
            try:
                if f.filter(event2, {}):
                    打印 = event2.get_extra(default={})
                    if "parsed_params" in 打印:
                        print(f"  {h.handler_name}: {打印['parsed_params']}")
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    报告()