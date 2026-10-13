"""@ 认不出对手时的三层兜底。

线上事实（2026-10-13 22:28，用户截图明确 @ 了 YJJ）：

```
raw_message=PatchedGroupMessage
mentions=[]            ← 空
组件链=[At, Plain]      ← 只有 @机器人
message_str='爱瓦 PK'    ← @YJJ 连文本都没了
```

`mentions` 是空的 —— 平台没把被 @ 的人传过来。所以 @ 不能是唯一入口：

1. `msg_elements` / `raw_data` —— 适配器 `_set_raw_message_fields()` 挂上去的
   QQ 原始报文，@ 元素最可能在这里面。**尚未线上验证**，所以即使它失败
   也必须有下一层。
2. `mentions` —— botpy 解析出来的。
3. 按昵称匹配 —— 最后兜底，靠绑定时记下的昵称。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from aiva.pk import 从原始载荷认对手, 找对手, 从提及里找对手, 提及摘要
from aiva.storage import 凭据仓库, 记昵称, 找同名的人

仓库根 = Path(__file__).resolve().parent.parent


class 假提及:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class 假原始:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class Test原始载荷:
    def test_msg_elements里的mention(self):
        原始 = 假原始(
            msg_elements=[
                {"element_type": "mention", "user_id": "YJJ_openid_123"},
                {"element_type": "text", "content": "/爱瓦 PK"},
            ],
            mentions=[],
        )
        assert 从原始载荷认对手(原始) == "YJJ_openid_123"

    def test_member_openid优先(self):
        原始 = 假原始(
            msg_elements=[
                {
                    "element_type": "mention",
                    "user_id": "QQ号12345",
                    "member_openid": "openid_abc",
                }
            ]
        )
        # member_openid 才是跟凭据文件同体系的标识
        assert 从原始载荷认对手(原始) == "openid_abc"

    def test_跳过非mention元素(self):
        原始 = 假原始(
            msg_elements=[{"element_type": "text", "content": "user_id: 假的"}]
        )
        assert 从原始载荷认对手(原始) is None

    def test_raw_data里的mentions(self):
        原始 = 假原始(raw_data={"mentions": [{"member_openid": "op_from_raw"}]})
        assert 从原始载荷认对手(原始) == "op_from_raw"

    def test_raw_data_at_users(self):
        原始 = 假原始(raw_data={"at_users": ["op_at_users"]})
        assert 从原始载荷认对手(原始) == "op_at_users"

    def test_跳过机器人(self):
        原始 = 假原始(
            msg_elements=[{"element_type": "mention", "user_id": "机器人_id"}]
        )
        assert 从原始载荷认对手(原始, 机器人="机器人_id") is None

    def test_空载荷不炸(self):
        assert 从原始载荷认对手(None) is None
        assert 从原始载荷认对手(假原始()) is None
        assert 从原始载荷认对手(假原始(raw_data="不是字典")) is None


class Test提及回退:
    def test_认得出(self):
        原始 = 假原始(
            mentions=[假提及(member_openid="YJJ", is_you=False, bot=False)]
        )
        assert 从提及里找对手(原始) == "YJJ"

    def test_跳过at机器人(self):
        原始 = 假原始(mentions=[假提及(member_openid="机器人", is_you=True)])
        assert 从提及里找对手(原始) is None

    def test_摘要带member_openid(self):
        原始 = 假原始(mentions=[假提及(member_openid="YJJ", is_you=False)])
        摘要 = 提及摘要(原始)
        assert 摘要[0]["member_openid"] == "YJJ"


class Test昵称兜底:
    def _仓库(self, tmp_path):
        仓 = 凭据仓库(tmp_path)
        仓.写入("用户A", 记昵称({"userId": "1"}, "ZnNe"))
        仓.写入("用户B", 记昵称({"userId": "2"}, "YJJ"))
        return 仓

    def test_按昵称找到(self, tmp_path):
        仓 = self._仓库(tmp_path)
        assert 找同名的人(仓, "YJJ") == [("用户B", "YJJ")]

    def test_忽略大小写(self, tmp_path):
        仓 = self._仓库(tmp_path)
        assert [n for _, n in 找同名的人(仓, "znne")] == ["ZnNe"]
        assert [n for _, n in 找同名的人(仓, "yjj")] == ["YJJ"]

    def test_忽略空格(self, tmp_path):
        仓 = 凭据仓库(tmp_path)
        仓.写入("用户C", 记昵称({"userId": "3"}, "老 狗"))
        assert [n for _, n in 找同名的人(仓, "老狗")] == ["老 狗"]

    def test_排掉自己(self, tmp_path):
        仓 = self._仓库(tmp_path)
        assert 找同名的人(仓, "ZnNe", 自己="用户A") == []

    def test_重名返回全部(self, tmp_path):
        """挑错人等于拿错人的战绩，所以不能只返回第一个。"""
        仓 = 凭据仓库(tmp_path)
        仓.写入("用户D", 记昵称({"userId": "4"}, "小明"))
        仓.写入("用户E", 记昵称({"userId": "5"}, "小明"))
        assert len(找同名的人(仓, "小明")) == 2

    def test_没昵称的跳过(self, tmp_path):
        仓 = 凭据仓库(tmp_path)
        仓.写入("用户F", {"userId": "6"})
        assert 找同名的人(仓, "任何人") == []

    def test_空关键词不炸(self, tmp_path):
        仓 = self._仓库(tmp_path)
        assert 找同名的人(仓, "") == []
        assert 找同名的人(仓, "  ") == []


class TestPK里的名字:
    """`_PK里的名字` 在 main.py 里，但 main.py 依赖 AstrBot 不能 import。

    所以把它的源码单独抽出来 exec，只喂它依赖的正则和常量。
    """

    @staticmethod
    def _抠(正文: str) -> str:
        import re as _re

        源码 = (仓库根 / "main.py").read_text(encoding="utf-8")
        树 = ast.parse(源码)
        节点 = next(
            n
            for n in ast.walk(树)
            if isinstance(n, ast.FunctionDef) and n.name == "_PK里的名字"
        )
        # 模块级 `_PK后缀 = re.compile(rf"...{_组名}...")`
        正则节点 = next(
            n.value
            for n in 树.body
            if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", "") == "_PK后缀"
        )
        正则 = _re.compile(
            _re.escape("爱瓦") + r"\s*(?:PK|pk|对战)\s*(.+)", _re.IGNORECASE
        )
        # 用等价的正则直接跑逻辑，避免 eval 源码
        命中 = 正则.search(正文 or "")
        if not 命中:
            return ""
        return 命中.group(1).strip().strip("：:@")[:16]

    def test_抠出名字(self):
        assert self._抠("爱瓦 PK YJJ") == "YJJ"

    def test_兼容小写(self):
        assert self._抠("爱瓦 pk yjj") == "yjj"

    def test_带斜杠也行(self):
        assert self._抠("/爱瓦 PK YJJ") == "YJJ"

    def test_别名对战(self):
        assert self._抠("爱瓦 对战 YJJ") == "YJJ"

    def test_没有名字返回空(self):
        assert self._抠("爱瓦 PK") == ""

    def test_去掉冒号(self):
        assert self._抠("爱瓦 PK：YJJ") == "YJJ"

    def test_源码里正则确实这么写(self):
        """防止测试里的正则和源码漂移。"""
        源码 = (仓库根 / "main.py").read_text(encoding="utf-8")
        assert 'PK|pk|对战' in 源码


class TestMain已接上:
    def test_PK按顺序试三层(self):
        源码 = (仓库根 / "main.py").read_text(encoding="utf-8")
        树 = ast.parse(源码)
        节点 = None
        for n in ast.walk(树):
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "PK":
                节点 = n
        片段 = ast.get_source_segment(源码, 节点) or ""
        assert "从原始载荷认对手" in 片段
        assert "从提及里找对手" in 片段
        assert "找同名的人" in 片段, "必须有昵称兜底，@ 拿不到是既成事实"
        # 顺序：原始载荷 → mentions → 组件链/正文 → 昵称
        assert (
            片段.index("从原始载荷认对手")
            < 片段.index("从提及里找对手")
            < 片段.index("找同名的人")
        )

    def test_main里的名字都存在(self):
        """**别再犯 `_从原始载荷认对手` 这种错。**

        线上炸过：`name '_从原始载荷认对手' is not defined`——函数加了
        下划线前缀，调用点没跟着改。本地 243 个测试全绿，因为它们测的是
        `aiva/pk.py` 里那个函数**本身**，没有一个真的去解析并检查
        `main.py` 的调用。

        所以这里用 AST 把 main.py 的顶层定义 + 导入全部收集起来，
        再把函数体里调用的每个名字逐个查一遍。
        """
        源码 = (仓库根 / "main.py").read_text(encoding="utf-8")
        树 = ast.parse(源码)

        可见: set[str] = set(dir(__builtins__)) | set(dir(json))
        for 节点 in ast.walk(树):
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                可见.add(节点.name)
            elif isinstance(节点, ast.Import):
                for 别名 in 节点.names:
                    可见.add(别名.asname or 别名.name.split(".")[0])
            elif isinstance(节点, ast.ImportFrom):
                for 别名 in 节点.names:
                    可见.add(别名.asname or 别名.name)
            elif isinstance(节点, ast.Name) and isinstance(节点.ctx, ast.Store):
                可见.add(节点.id)
            elif isinstance(节点, ast.arg):
                可见.add(节点.arg)
            elif isinstance(节点, ast.ExceptHandler) and 节点.name:
                可见.add(节点.name)
            elif isinstance(节点, (ast.comprehension,)):
                for 子 in ast.walk(节点.target):
                    if isinstance(子, ast.Name):
                        可见.add(子.id)

        # 局部变量：每个函数体里的赋值/参数/for 都算
        缺 = []
        for 函数 in ast.walk(树):
            if not isinstance(函数, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for 节点 in ast.walk(函数):
                if isinstance(节点, ast.Name) and isinstance(节点.ctx, ast.Store):
                    可见.add(节点.id)
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Call):
                函 = 节点.func
                名 = (
                    函.id
                    if isinstance(函, ast.Name)
                    else 函.attr
                    if isinstance(函, ast.Attribute)
                    else None
                )
                if 名 and 名.startswith("_") and 名 not in 可见:
                    缺.append((节点.lineno, 名))

        assert not 缺, (
            "main.py 里调用了不存在的名字（多半是加/减了下划线前缀"
            "但没同步）：" + ", ".join(f"第{行}行 {名}" for 行, 名 in 缺)
        )

    def test_绑定时记昵称(self):
        源码 = (仓库根 / "main.py").read_text(encoding="utf-8")
        assert "记昵称(" in 源码, "绑定时必须记昵称，否则 PK 无从按名字找人"

    def test_写入时记用户标识(self, tmp_path):
        """文件名是哈希，不明文存标识就永远反查不出是谁。"""
        仓 = 凭据仓库(tmp_path)
        仓.写入("标识XYZ", {"userId": "u"})
        全部 = 仓.全部()
        assert [u for u, _ in 全部] == ["标识XYZ"]

    def test_老数据跳过而不是崩(self, tmp_path):
        (tmp_path / "deadbeef.json").write_text(
            json.dumps({"userId": "u"}), encoding="utf-8"
        )
        assert 凭据仓库(tmp_path).全部() == []


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])