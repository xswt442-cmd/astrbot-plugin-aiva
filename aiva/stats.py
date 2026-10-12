"""把掌瓦的对局列表聚成一组可以直接念出来的指标。

**原则：这里算出来的数字是最终答案。** 模型只负责照着说，
不许重算、不许「约」「大概」、不许补一个这里没给的数。

字段名来自第三方那份 `API_FIELDS.md`（标称基于掌瓦 2.7.1.10064），
本仓库 **尚未用自己的登录态逐字段核对过**——首次绑定后要用
`test/verify_mval.py` 跑一遍，对不上的地方回来改这里，不要改提示词去迁就。

两处已知的坑，写在最前面：

1. `kda` 是 `"13/18/10"` 这种**字符串**，不是三个整数。
2. `result_title` 是 `"获胜"` / `"失败"` / `"平局"` 的**中文**，别按首字母判断。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "一场",
    "拆KDA",
    "看胜负",
    "聚合",
    "对比要点",
    "对比文本",
    "占优项数",
    "地图一览",
    "近期走势",
    "近况文本",
    "特工一览",
    "场次数上限",
    "是否计分模式",
]

# 掌瓦只对自己的一个 account 返回最近若干场，取太多会拖慢，
# 而模型面对 40 场也不会比 20 场说得更好。
场次数上限 = 20

# 只统计这两种模式的对局。死斗/斗牛/爆能快攻的 KDA 与 ACS 量纲不同，
# 混进来会把均值拉成一个没有意义的数字。
_计分模式 = frozenset({"competitive", "unrated", "premier", "swiftplay"})

_胜_txt = frozenset({"获胜", "胜利", "胜"})
_败_txt = frozenset({"失败", "落败", "负"})
_平_txt = frozenset({"平局", "和"})


class 一场:
    """单局数据的一个薄壳。字段缺失一律给 None / 0，**不猜**。"""

    __slots__ = (
        "模式",
        "地图",
        "胜负",
        "击杀",
        "死亡",
        "助攻",
        "ACS",
        "评分等级",
        "特工",
        "己方回合",
        "对方回合",
        "时间",
    )

    def __init__(self, 原始: dict[str, Any]) -> None:
        self.模式 = str(原始.get("game_mode") or "")
        self.地图 = ((原始.get("used_map") or {}).get("name") or "").strip()
        self.胜负 = 看胜负(原始.get("result_title"))
        self.击杀, self.死亡, self.助攻 = 拆KDA(原始.get("kda"))
        self.ACS = _转数(原始.get("score_avg"))
        等级 = 原始.get("score_level") or {}
        self.评分等级 = str(等级.get("level") or "").strip()
        特工 = str(原始.get("hero_name") or "").strip()
        self.特工 = 特工 or "—"
        self.己方回合 = _转数(原始.get("round_won"))
        self.对方回合 = _转数(原始.get("round_fail"))
        self.时间 = str(原始.get("time") or "")

    @property
    def KDA比值(self) -> float:
        if self.死亡 <= 0:
            # 0 死不该除出 Infinity，也不能记 0 分。按「击杀+助攻」处理，
            # 写清这是它的上限而不是真实比值。
            return float(self.击杀 + self.助攻)
        return (self.击杀 + self.助攻) / self.死亡


def 是否计分模式(原始: dict[str, Any]) -> bool:
    """只留完整的 5v5 回合制模式。"""
    枚举 = str(原始.get("game_enum") or "").strip().lower()
    if not 枚举:
        # 没给枚举时按中文模式名兜底：里面含「死斗」「斗牛」的一律不要。
        模式 = str(原始.get("game_mode") or "")
        return not any(词 in 模式 for 词 in ("死斗", "斗牛", "单人"))
    return 枚举 in _计分模式


def 看胜负(文本: Any) -> str:
    """把 result_title 归一成 胜/负/平/未知。"""
    值 = str(文本 or "").strip()
    if 值 in _胜_txt:
        return "胜"
    if 值 in _败_txt:
        return "负"
    if 值 in _平_txt:
        return "平"
    return "未知"


def 拆KDA(值: Any) -> tuple[int, int, int]:
    """`"13/18/10"` → (13, 18, 10)。

    拆不动就记 (0, 0, 0)，但上层要把这种局排除掉，避免拉低均值。
    """
    if isinstance(值, (list, tuple)) and len(值) >= 3:
        三 = 值[:3]
    else:
        三 = str(值 or "").split("/")
    if len(三) < 3:
        return (0, 0, 0)
    try:
        return (_转数(三[0]), _转数(三[1]), _转数(三[2]))
    except (TypeError, ValueError):
        return (0, 0, 0)


def _转数(值: Any) -> float:
    """字段类型在 string/int 之间摇摆（同一个字段不同场次可能不同），统一转。"""
    if 值 is None or 值 == "":
        return 0.0
    if isinstance(值, (int, float)):
        return float(值)
    try:
        return float(str(值).replace("%", "").replace(",", "").strip())
    except ValueError:
        return 0.0


def 聚合(原始列表: list[Any]) -> dict[str, Any]:
    """把一页原始数据聚成一份摘要。

    返回的东西**全部是算好的值**，模型照抄即可。缺失的项一律 None，
    让它说「这一项没有」，而不是让它自己估一个。
    """
    全部: list[一场] = []
    for 项 in 原始列表 or []:
        if not isinstance(项, dict):
            continue
        if not 是否计分模式(项):
            continue
        一场数据 = 一场(项)
        if 一场数据.击杀 == 0 and 一场数据.死亡 == 0 and 一场数据.助攻 == 0:
            # KDA 拆不出来的局直接丢掉：均值会被一堆 0 拉到毫无意义。
            continue
        全部.append(一场数据)

    场数 = len(全部)
    if 场数 == 0:
        return {"场数": 0}

    胜 = sum(1 for g in 全部 if g.胜负 == "胜")
    负 = sum(1 for g in 全部 if g.胜负 == "负")
    平 = sum(1 for g in 全部 if g.胜负 == "平")

    def 均值(取) -> float:
        return round(sum(取(g) for g in 全部) / 场数, 1)

    ACS列表 = [g.ACS for g in 全部 if g.ACS > 0]
    return {
        "场数": 场数,
        "胜": 胜,
        "负": 负,
        "平": 平,
        "胜率": round(胜 / max(胜 + 负, 1) * 100, 1),
        "场均击杀": 均值(lambda g: g.击杀),
        "场均死亡": 均值(lambda g: g.死亡),
        "场均助攻": 均值(lambda g: g.助攻),
        "KDA": round(sum(g.KDA比值 for g in 全部) / 场数, 2),
        "场均ACS": round(sum(ACS列表) / len(ACS列表), 1) if ACS列表 else None,
        "场均回合差": round(sum(g.己方回合 - g.对方回合 for g in 全部) / 场数, 1),
        "地图": 地图一览(全部),
        "特工": 特工一览(全部),
        "走势": 近期走势(全部),
    }


def 地图一览(局: list[一场]) -> list[dict[str, Any]]:
    """按地图聚合场次与胜率，按场次降序。"""
    表: dict[str, dict[str, Any]] = {}
    for g in 局:
        名 = g.地图 or "未知"
        行 = 表.setdefault(名, {"地图": 名, "场次": 0, "胜": 0})
        行["场次"] += 1
        if g.胜负 == "胜":
            行["胜"] += 1
    for 行 in 表.values():
        行["胜率"] = round(行["胜"] / 行["场次"] * 100, 1)
    return sorted(表.values(), key=lambda r: -r["场次"])


def 特工一览(局: list[一场], 前几: int = 5) -> list[dict[str, Any]]:
    """按特工聚合，取用得最多的几个。"""
    表: dict[str, dict[str, Any]] = {}
    for g in 局:
        行 = 表.setdefault(g.特工, {"特工": g.特工, "场次": 0, "胜": 0, "_ACS": 0.0, "_n": 0})
        行["场次"] += 1
        if g.胜负 == "胜":
            行["胜"] += 1
        if g.ACS > 0:
            行["_ACS"] += g.ACS
            行["_n"] += 1
    出: list[dict[str, Any]] = []
    for 行 in 表.values():
        行["胜率"] = round(行["胜"] / 行["场次"] * 100, 1)
        行["场均ACS"] = round(行["_ACS"] / 行["_n"], 1) if 行["_n"] else None
        出.append({k: v for k, v in 行.items() if not k.startswith("_")})
    出.sort(key=lambda r: -r["场次"])
    return 出[:前几]


def 近期走势(局: list[一场], 取: int = 10) -> list[str]:
    """最近若干场的胜负序列，**按原始数据顺序**，最前面是最新的一场。

    掌瓦的列表本来就是倒序（新的在前）。这里不做任何额外排序，
    免得把「最近五连败」排成别的样子。
    """
    return [g.胜负 for g in 局[:取]]


def 对比要点(甲: dict[str, Any], 乙: dict[str, Any]) -> list[dict[str, str]]:
    """逐项比出高低。返回 `[{"项":…, "甲":…, "乙":…, "优":"甲"|"乙"|"持平"}]`。

    对比**由代码算死，不交给模型**：让模型自己比，它最省事的答案就是
    「各有千秋」这类端水话。每项都算清谁占优、双方数字多少，模型的活只剩
    解说，端水就没地方藏。
    """
    要点: list[dict[str, str]] = []

    # 有一方没数据就不比。空统计里各项都是 None，逐项比下来是一串
    # 「持平」，看着像「两人一样强」，其实是「没数据」。
    if not 甲.get("场数") or not 乙.get("场数"):
        return 要点

    def 一项(
        标题: str,
        甲值: float | None,
        乙值: float | None,
        *,
        越小越好: bool = False,
        单位: str = "",
        位数: int = 1,
    ) -> None:
        if 甲值 is None or 乙值 is None:
            return
        模板 = f"{{:.{位数}f}}"
        甲文 = 模板.format(甲值) + 单位
        乙文 = 模板.format(乙值) + 单位
        if 甲值 == 乙值:
            优 = "持平"
        elif (甲值 > 乙值) != 越小越好:
            优 = "甲"
        else:
            优 = "乙"
        要点.append({"项": 标题, "甲": 甲文, "乙": 乙文, "优": 优})

    一项("胜率", 甲.get("胜率"), 乙.get("胜率"), 单位="%")
    一项("KDA", 甲.get("KDA"), 乙.get("KDA"), 位数=2)
    一项("场均ACS", 甲.get("场均ACS"), 乙.get("场均ACS"))
    一项("场均击杀", 甲.get("场均击杀"), 乙.get("场均击杀"))
    一项("场均死亡", 甲.get("场均死亡"), 乙.get("场均死亡"), 越小越好=True)
    一项("场均助攻", 甲.get("场均助攻"), 乙.get("场均助攻"))
    一项("回合净胜", 甲.get("场均回合差"), 乙.get("场均回合差"))
    一项("统计场数", 甲.get("场数"), 乙.get("场数"), 位数=0, 单位=" 场")
    return 要点


def 对比文本(要点: list[dict[str, str]], 甲名: str, 乙名: str) -> str:
    """把对比要点折成给模型读的文本。每一行都直接说明谁占优。"""
    行 = []
    for 条 in 要点:
        if 条["优"] == "持平":
            行.append(f"{条['项']}：持平（{甲名} {条['甲']} / {乙名} {条['乙']}）")
        else:
            优名 = 甲名 if 条["优"] == "甲" else 乙名
            行.append(f"{条['项']}：{优名}占优（{甲名} {条['甲']} / {乙名} {条['乙']}）")
    return "\n".join(行)


def 占优项数(要点: list[dict[str, str]], 甲名: str, 乙名: str) -> str:
    """「甲 5 项、乙 2 项」这样的汇总，写进提示里当参考。

    刻意**不**把它写成「占优多的一方必须赢」：项数是机械数出来的，而实际谁更强
    要看是哪几项——赢面判断留给模型，这里只提供事实。
    """
    甲数 = sum(1 for 条 in 要点 if 条["优"] == "甲")
    乙数 = sum(1 for 条 in 要点 if 条["优"] == "乙")
    return f"{甲名} {甲数} 项、{乙名} {乙数} 项"


def 近况文本(摘要: dict[str, Any]) -> str:
    """把摘要拼成一段给模型的文本。

    这一段是模型的**全部事实来源**：这里没有的数字，它就不该说。
    """
    if not 摘要.get("场数"):
        return "（没有可统计的对局）"

    行 = [
        f"近 {摘要['场数']} 场：{摘要['胜']}胜 {摘要['负']}负"
        + (f" {摘要['平']}平" if 摘要.get("平") else ""),
        f"胜率 {摘要['胜率']}%",
        f"场均 K/D/A {摘要['场均击杀']}/{摘要['场均死亡']}/{摘要['场均助攻']}（KDA {摘要['KDA']}）",
    ]
    if 摘要.get("场均ACS") is not None:
        行.append(f"场均 ACS {摘要['场均ACS']}")
    else:
        行.append("场均 ACS 未取到")

    行.append(f"场均回合净胜 {摘要['场均回合差']}")

    if 摘要.get("走势"):
        符号 = {"胜": "W", "负": "L", "平": "D", "未知": "?"}
        行.append("最近走势 " + " ".join(符号.get(s, "?") for s in 摘要["走势"]))

    if 摘要.get("地图"):
        地图片 = "、".join(f"{r['地图']} {r['场次']}场/{r['胜率']}%" for r in 摘要["地图"][:5])
        行.append(f"地图 {地图片}")

    if 摘要.get("特工"):
        特工片 = "、".join(
            f"{r['特工']} {r['场次']}场"
            + (f"/{r['场均ACS']} ACS" if r["场均ACS"] is not None else "")
            for r in 摘要["特工"]
        )
        行.append(f"常用特工 {特工片}")

    return "\n".join(行)
