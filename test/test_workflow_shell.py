"""工作流里的 shell 片段必须用 ASCII 变量名。

GitHub runner 的 bash 与 awk 都不接受非 ASCII 的标识符：

- `bash -c '版本=v0.1.4'` 直接 `command not found`，`$版本` 展开成空，
  于是 `[[ ! "" =~ ^v... ]]` 判定失败，报出来的错误信息还是那句正确的
  提示，看起来像版本号写错了，其实是变量根本没赋值。
- `awk` 里的中文变量名报 `invalid char`，整步失败。

这个错在 release 工作流上连踩两次：第一次是 awk，改掉后没检查 bash 里的
变量，触发时立刻失败。所以在这里扫全，文本内容（echo 的中文、注释）不受限制。
"""

from __future__ import annotations

import re
from pathlib import Path

工作流目录 = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# bash 的变量赋值与引用：NAME= / $NAME / ${NAME} / $'...' 之外的普通形式
_赋值 = re.compile(r"^\s*(?:export\s+)?([^\s=]+)=")
_引用 = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
_内建 = {
    "BASH",
    "PATH",
    "HOME",
    "GITHUB",
    "RUNNER",
    "CI",
    "PWD",
    "USER",
    "TMPDIR",
    "IFS",
    "RANDOM",
    "SECONDS",
    "LINENO",
    "PIPESTATUS",
    "ver",
    "bare",
    "meta",
    "pkgver",
    "latest",
    "bytes",
    "grep",
    "unzip",
    "du",
    "stat",
    "cut",
    "awk",
    "echo",
    "git",
    "gh",
    "sleep",
    "seq",
    "docker",
    "uv",
    "npm",
    "node",
}


def _逐步检查(名称: str, 原文: str) -> list[str]:
    """只看 run: 块里的 shell，YAML 结构和 echo 的中文不算。"""
    问题: list[str] = []
    在脚本里 = False
    for 行号, 行 in enumerate(原文.splitlines(), 1):
        if not 在脚本里:
            if re.match(r"^\s*run:\s*\|", 行):
                在脚本里 = True
            continue

        赋值 = _赋值.match(行)
        if 赋值 and not 赋值.group(1).isascii():
            问题.append(f"{名称}:{行号} 变量名非 ASCII：{赋值.group(1)}")

        for 变量 in _引用.findall(行):
            if not 变量.isascii():
                问题.append(f"{名称}:{行号} 引用非 ASCII 变量：${变量}")

    return 问题


def test_工作流里的_shell_变量名都是_ascii():
    问题: list[str] = []
    for 路径 in sorted(工作流目录.glob("*.yml")):
        问题 += _逐步检查(路径.name, 路径.read_text(encoding="utf-8"))
    assert not 问题, "bash 不接受非 ASCII 变量名，改用 ASCII：\n" + "\n".join(问题)


def test_工作流目录非空():
    """确认 glob 没写错，否则上面那条会静默通过。"""
    assert list(工作流目录.glob("*.yml")), f"{工作流目录} 下没有找到工作流文件"
