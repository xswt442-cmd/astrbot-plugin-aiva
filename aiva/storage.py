"""绑定信息的本地存储。

一个 Bot 用户一份文件，存的是**他自己的登录凭据**：openid、access_token、
userId、tid。这些串都能用来查他的战绩，所以：

- 文件权限收紧到只有属主能读（0o600）；
- 任何对外的地方（repr / 日志 / 异常消息）都不许带凭据本体；
- 解绑即删文件，不留备份。

文件名是用户标识的 SHA-256 摘要：QQ 号、微信 openid 里可能出现斜杠和
`@`，直接拿来拼路径会写错地方甚至越级。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

__all__ = ["凭据仓库", "凭据是否齐全", "凭据摘要"]

_文件后缀 = ".json"

# 查战绩必须这四样齐全。缺任何一样都判为「没绑好」，让用户重扫——
# 而不是带着半份凭据去打接口，拿一个不明就里的错误回来。
_必备字段 = ("openid", "access_token", "userId", "tid")


def 凭据是否齐全(凭据: dict[str, Any] | None) -> bool:
    if not 凭据:
        return False
    return all(str(凭据.get(字段) or "").strip() for 字段 in _必备字段)


def 凭据摘要(凭据: dict[str, Any]) -> str:
    """给用户看的一行：有 userId 就显示 userId，不带任何令牌。"""
    用户 = str(凭据.get("userId") or "").strip()
    if 用户 and len(用户) > 10:
        return f"{用户[:6]}…{用户[-4:]}"
    return 用户 or "（未知）"


class 凭据仓库:
    def __init__(self, 目录: Path) -> None:
        self.目录 = 目录

    def 路径(self, 用户: str) -> Path:
        摘要 = hashlib.sha256(用户.encode("utf-8")).hexdigest()[:32]
        return self.目录 / f"{摘要}{_文件后缀}"

    def 读取(self, 用户: str) -> dict[str, Any] | None:
        路径 = self.路径(用户)
        try:
            载荷 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return 载荷 if isinstance(载荷, dict) else None

    def 写入(self, 用户: str, 凭据: dict[str, Any]) -> None:
        路径 = self.路径(用户)
        路径.parent.mkdir(parents=True, exist_ok=True)
        载荷 = json.dumps(凭据, ensure_ascii=False, indent=2)
        # 临时文件 + 替换：写到一半崩了也不会留下半个凭据文件。
        临时 = 路径.with_suffix(f"{_文件后缀}.tmp")
        临时.write_text(载荷, encoding="utf-8")
        os.replace(临时, 路径)
        try:
            os.chmod(路径, 0o600)
        except OSError:
            # Windows 上 chmod 不是完整 ACL；任务失败不影响可用性。
            pass

    def 删除(self, 用户: str) -> bool:
        路径 = self.路径(用户)
        try:
            路径.unlink()
        except FileNotFoundError:
            return False
        except OSError:
            return False
        return True
