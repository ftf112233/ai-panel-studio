"""核心逻辑单测（TDD）：嘉宾生成、发言调度、共识/分歧提炼。

零第三方依赖：unittest + asyncio + 桩 LLM。
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.director import DirectorAgent
from app.agents.insight import merge_insights
from app.agents.lineup import LineupAgent
from app.llm.client import MockLLMClient
from app.storage.db import Expert, Lineup


class ScriptedLLM:
    """按队列返回 JSON 字符串；队列用尽后返回空串（模拟模型输出非法）。"""

    def __init__(self, script=None):
        self.script = list(script or [])

    async def json_chat(self, messages, temperature=0.7):
        return {"text": self.script.pop(0) if self.script else "这不是 JSON"}

    async def stream_chat(self, messages, temperature=0.9):
        for ch in "短发言测试。":
            yield ch


def make_experts(n=4):
    return [Expert(id=f"e{i + 1}", name=f"专家{i + 1}", occupation="领域", title="头衔",
                   stance=f"立场{i + 1}", color="#111111") for i in range(n)]


# ---------------------------------------------------------------- 嘉宾生成
class TestLineup(unittest.TestCase):
    def test_generate_with_valid_llm_output(self):
        llm = ScriptedLLM([('{"host": {"name": "知遥", "title": "主持人"}, "experts": ['
                            '{"name": "A", "occupation": "AI", "title": "创业者", "stance": "乐观"},'
                            '{"name": "B", "occupation": "IT", "title": "CTO", "stance": "谨慎"}]}')])
        lineup = asyncio.run(LineupAgent(llm).generate("测试话题", 2))
        self.assertEqual(len(lineup.experts), 2)
        self.assertEqual(lineup.experts[0].name, "A")
        self.assertNotEqual(lineup.experts[0].color, lineup.experts[1].color)  # 颜色不重复

    def test_invalid_output_falls_back_to_pool(self):
        """模型返回垃圾时仍要凑够人数（降级链的最后一层）。"""
        lineup = asyncio.run(LineupAgent(ScriptedLLM([])).generate("测试话题", 3))
        self.assertEqual(len(lineup.experts), 3)
        self.assertTrue(all(e.name and e.occupation for e in lineup.experts))

    def test_count_clamped_and_padded(self):
        """人数不足时用内置池补齐；上限 5。"""
        llm = ScriptedLLM(['{"host": {}, "experts": [{"name": "A", "occupation": "x", "title": "y", "stance": "z"}]}'])
        lineup = asyncio.run(LineupAgent(llm).generate("话题", 4))
        self.assertEqual(len(lineup.experts), 4)
        lineup5 = asyncio.run(LineupAgent(ScriptedLLM([])).generate("话题", 9))
        self.assertEqual(len(lineup5.experts), 5)

    def test_mock_client_deterministic(self):
        a = asyncio.run(LineupAgent(MockLLMClient()).generate("同一个话题", 4))
        b = asyncio.run(LineupAgent(MockLLMClient()).generate("同一个话题", 4))
        self.assertEqual([e.name for e in a.experts], [e.name for e in b.experts])


# ---------------------------------------------------------------- 发言调度
class TestDirector(unittest.TestCase):
    def test_pick_returns_valid_speaker(self):
        experts = make_experts(4)
        llm = ScriptedLLM(['{"speaker": "e2", "action": "rebut", "thought": "我要反驳"}'])
        d = DirectorAgent(llm, "话题", experts)
        pick = asyncio.run(d.pick("焦点", "最近发言", "e1"))
        self.assertEqual(pick["speaker"], "e2")
        self.assertEqual(pick["action"], "rebut")
        self.assertTrue(pick["thought"])

    def test_never_picks_last_speaker(self):
        """需求：不允许机械轮流 / 连续同一个人。"""
        experts = make_experts(3)
        d = DirectorAgent(ScriptedLLM([]), "话题", experts)  # 恒返回非法输出
        seen = []
        last = None
        for _ in range(6):
            pick = asyncio.run(d.pick("焦点", "", last))
            self.assertNotEqual(pick["speaker"], last)
            seen.append(pick["speaker"])
            last = pick["speaker"]
        self.assertEqual(len(set(seen)), 3)  # 三人都被轮到过（确定性补位）

    def test_invalid_action_normalized(self):
        d = DirectorAgent(ScriptedLLM(['{"speaker": "e1", "action": "乱来"}']), "话题", make_experts(2))
        pick = asyncio.run(d.pick("焦点", "", "e2"))
        self.assertIn(pick["action"], {"raise_hand", "supplement", "rebut"})


# ---------------------------------------------------------------- 共识/分歧
class TestInsight(unittest.TestCase):
    def test_merge_dedupes(self):
        merged = merge_insights(["已有共识"], [], {"consensus": ["已有共识", "新共识"], "disagreements": []})
        self.assertEqual(merged["consensus"], ["已有共识", "新共识"])
        merged2 = merge_insights(merged["consensus"], [], {"consensus": ["已有共识"], "disagreements": []})
        self.assertEqual(merged2["consensus"], ["已有共识", "新共识"])  # 重复被丢弃

    def test_merge_rejects_garbage(self):
        merged = merge_insights([], [], {"consensus": ["短", None, 123], "disagreements": [
            {"a": "A", "b": "B"}, {"a": "A", "b": "B", "point": "太短"}]})
        self.assertEqual(merged["consensus"], [])
        self.assertEqual(merged["disagreements"], [])

    def test_merge_caps_size(self):
        existing = [f"共识{i}" for i in range(6)]
        merged = merge_insights(existing, [], {"consensus": ["再一条"], "disagreements": []})
        self.assertEqual(len(merged["consensus"]), 6)
        self.assertNotIn("共识0", merged["consensus"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
