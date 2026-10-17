"""`_conf_schema.json` 与代码是否对得上。

配置项有两种坏法：代码读一个 schema 里没有的键（用户在 WebUI 里根本看不到），
或者 schema 里摆一个没人读的键（改了没反应，还让人以为功能存在）。
两边都钉住。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent
schema = json.loads((仓库根 / "_conf_schema.json").read_text(encoding="utf-8"))
主源码 = (仓库根 / "main.py").read_text(encoding="utf-8")


def _代码读的键() -> set[str]:
    键 = set(re.findall(r"config\.get\(\s*[\"']([^\"']+)[\"']", 主源码))
    键 |= set(re.findall(r"_配置(?:整数|开关)\(\s*config\s*,\s*[\"']([^\"']+)[\"']", 主源码))
    return 键


def test_代码读的键都在_schema_里():
    缺 = _代码读的键() - set(schema)
    assert not 缺, f"这些键代码在读，但 schema 里没有，用户看不到：{sorted(缺)}"


def test_schema_里没有没人读的键():
    多余 = set(schema) - _代码读的键()
    assert not 多余, f"这些配置项没人读，改了不会有任何反应：{sorted(多余)}"


def test_每项都有类型说明与默认值():
    for 键, 项 in schema.items():
        assert 项.get("type"), f"{键} 缺 type"
        assert 项.get("description"), f"{键} 缺 description"
        assert "default" in 项, f"{键} 缺 default"
        assert 项.get("hint"), f"{键} 缺 hint，用户在 WebUI 里不知道该怎么填"


def test_类型是框架认的那几种():
    允许 = {"string", "int", "float", "bool", "text", "list", "dict", "file"}
    坏的 = {键: 项.get("type") for 键, 项 in schema.items() if 项.get("type") not in 允许}
    assert not 坏的, f"这些类型 AstrBot 不认：{坏的}"
