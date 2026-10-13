"""提示词的措辞。

这些不是「文案好不好」的审美测试，而是**格式、反端水与反编造约束**：称号那
一行要以「你最近是个」开头，PK 不许推翻算好的对比，开一局必须写明是推演，
段位只能照抄数据。

模型很爱把这些约束自由发挥掉，改了提示就靠这几条兜住。
"""

from __future__ import annotations

from aiva.prompts import PK提示, 字段白名单, 开局提示, 推演声明, 称号前缀, 端水词, 锐评提示

数据 = "当前段位 铂金3 ｜ 近20场 11胜9负 ｜ 胜率 55% ｜ KDA 1.42 ｜ ACS 231"

_对比 = "ACS：甲占优（甲 231 / 乙 198）\nKDA：甲占优（甲 1.42 / 乙 1.10）"
_占优 = "甲 2 项、乙 0 项"


class Test锐评提示:
    提示 = 锐评提示(数据)

    def test_带上数据(self):
        assert 数据 in self.提示

    def test_称号行有硬前缀(self):
        assert 称号前缀 in self.提示
        assert 称号前缀 == "你最近是个"

    def test_三个小标题都在(self):
        for 段 in ("打得好：", "问题：", "建议："):
            assert 段 in self.提示, f"缺小标题 {段}"

    def test_要求不要前言(self):
        assert "不要前言" in self.提示

    def test_要求出现具体数字(self):
        assert "至少出现 3 个具体数字" in self.提示

    def test_段位只能照抄数据(self):
        """编一个段位比不写段位恶劣得多：玩家会以为自己真是那一个段。"""
        assert "段位只能照抄数据里的「当前段位」那一句" in self.提示
        assert "编一个段位比不写段位恶劣得多" in self.提示

    def test_禁掉了端水词(self):
        for 词 in 端水词:
            assert 词 in self.提示, f"端水词「{词}」应该写进禁令里"

    def test_不许编数据里没有的东西(self):
        assert "只说数据支撑得住的话" in self.提示
        assert "宁可少说一句，也不要编一句" in self.提示

    def test_字段白名单写进了提示(self):
        """掌瓦没有 ADR、KAST、经济，不写清楚模型会照 CS2 那套指标编。"""
        for 段 in 字段白名单.split("。"):
            if 段.strip():
                assert 段.strip() in self.提示

    def test_白名单里点名了没有的维度(self):
        for 维度 in ("ADR", "KAST", "经济"):
            assert 维度 in 字段白名单

    def test_有字数区间(self):
        assert "180 到 260 字" in self.提示


class Test开局提示:
    提示 = 开局提示("设定")

    def test_必须写明这是推演(self):
        """用户看到一串 K/D/A 看不出真假，第一行那句话是唯一的提示。"""
        assert self.提示.count(推演声明) >= 2
        assert "不是真实战绩" in self.提示

    def test_硬要求里写了不许省略(self):
        assert f"第一行必须是「{推演声明}」" in self.提示
        assert "不许改写、不许省略" in self.提示

    def test_四个小标题都在(self):
        for 段 in ("经过：", "亮点：", "问题：", "复盘："):
            assert 段 in self.提示, f"缺小标题 {段}"

    def test_亮点与问题都要带数字(self):
        assert "各必须出现设定里的至少一个数字" in self.提示

    def test_不许编数据里没有的东西(self):
        assert "只说数据支撑得住的话" in self.提示


class TestPK提示:
    def _提示(self) -> str:
        return PK提示("老王", "小明", _对比, _占优, "老王数据", "小明数据")

    def test_明确不许推翻已算好的对比(self):
        """让模型自己比，它最省事的答案就是「各有千秋」。"""
        提示 = self._提示()

        assert "不要推翻对比结论" in 提示
        assert "已经替你算好了" in 提示

    def test_要求写出双方数字(self):
        assert "必须写出项名与双方数字" in self._提示()

    def test_占优项数只作参考不判定胜负(self):
        提示 = self._提示()

        assert "占优项更多的一方不一定分数更高" in 提示
        assert "仅供参考" in 提示

    def test_分差要跟实际差距相符(self):
        """分差不该为了制造对立硬拉开，两人本来就接近时就该接近。"""
        提示 = self._提示()

        assert "分差要跟两人的实际差距相符" in 提示
        assert "敢于给大的分数差距" not in 提示

    def test_胜者要与分数一致(self):
        """分数与胜者由模型各写各的，不钉住就会出现 88 分输给 70 分。"""
        提示 = self._提示()

        assert "胜者那一行写分数更高的那个人" in 提示
        assert "老王 或 小明" in 提示

    def test_双方数据都在提示里(self):
        提示 = self._提示()

        assert "【老王】原始数据\n老王数据" in 提示
        assert "【小明】原始数据\n小明数据" in 提示

    def test_端水词列成禁令(self):
        提示 = self._提示()

        for 词 in 端水词:
            assert 词 in 提示

    def test_不许编数据里没有的东西(self):
        assert "只说数据支撑得住的话" in self._提示()

    def test_互损要有字数下限(self):
        assert "至少 90 字" in self._提示()
