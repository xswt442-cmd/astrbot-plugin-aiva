"""在AstrBot 容器里实测爱瓦指令的 filter 链。

单独跑一个进程时 `star_handlers_registry` 是空的（插件是主进程加载的），
所以这里直接 import 插件的 main，让装饰器把 filter 建出来，再拿它跑候选消息。

用法（在容器内）：
    cd /AstrBot/data/plugins/astrbot_plugin_aiva && python test/探针.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/AstrBot")
sys.path.insert(0, "/AstrBot/data/plugins/astrbot_plugin_aiva")

import data.plugins.astrbot_plugin_aiva.main as 爱瓦插件  # noqa: E402
from astrbot.core.platform.astr_message_event import AstrMessageEvent  # noqa: E402
from astrbot.core.platform.astrbot_message import (  # noqa: E402
    AstrBotMessage,
    MessageType,
)
from astrbot.core.platform.platform_metadata import PlatformMetadata  # noqa: E402
from astrbot.core.star.filter.command import CommandFilter  # noqa: E402
from astrbot.core.star.filter.command_group import (  # noqa: E402
    CommandGroupFilter,
)

候选 = [
    "/爱瓦 绑定",
    "爱瓦 绑定",
    "[At:qq_official] /爱瓦 绑定",
]


def 造事件(文本: str) -> AstrMessageEvent:
    msg = AstrBotMessage()
    msg.type = MessageType.GROUP_MESSAGE
    e = AstrMessageEvent(
        message_str=文本,
        message_obj=msg,
        platform_meta=PlatformMetadata("qq_official", "lg1", "lg1"),
        session_id="ZnNe/2A8FDBA44C38D5B4863B0F49D76E744E",
    )
    e.is_at_or_wake_command = True
    return e


def 主():
    # 装饰器建出来的组挂在 RegisteringCommandable 上
    实例 = 爱瓦插件.Main.__new__(爱瓦插件.Main)
    组 = 实例.爱瓦.parent_group
    assert isinstance(组, CommandGroupFilter)
    print("指令组完整名：", 组.get_complete_command_names())
    print("custom_filter：", [type(c).__name__ for c in 组.custom_filter_list])
    子 = 组.sub_command_filters
    print("子命令：", [s.command_name for s in 子])
    print("子命令 custom_filter 数：", [len(s.custom_filter_list) for s in 子])
    print()

    # 组上的 filter + 每个子指令的 filter，合成 waking_check 实际跑的链路
    链路 = [("组", 组)] + [(s.command_name, s) for s in 子]

    for 文本 in 候选:
        print(f"===== message_str = {文本!r} =====")
        for 名, f in 链路:
            event = 造事件(文本)
            try:
                r = f.filter(event, {})
            except Exception as e:  # noqa: BLE001
                print(f"  {名}: 抛错 {type(e).__name__}: {e}")
                continue
            额外 = ""
            if isinstance(f, CommandFilter) and event.get_extra(default={}).get("parsed_params"):
                额外 = f" params={event.get_extra(default={})['parsed_params']}"
            print(f"  {'✅' if r else '— '} {名}: {r}{额外}")
        print()


if __name__ == "__main__":
    主()
