"""编排器单测：状态机收敛、非机械轮流、状态小窗事件、共识实时更新、短发言。"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Settings
from app.context import visible_history
from app.llm.client import MockLLMClient
from app.orchestrator import Orchestrator
from app.storage.db import Expert, Lineup, Message, Repository

TOPIC = "AI 编程工具会取代初级程序员吗？"


def make_lineup(n=4) -> Lineup:
    return Lineup(host_name="知遥", host_title="主持人", experts=[
        Expert(id=f"e{i + 1}", name=f"专家{i + 1}", occupation="领域", title="头衔",
               stance=f"立场{i + 1}", color="#111111") for i in range(n)])


def make_settings(tmp, **kw):
    s = Settings()
    s.db_path = os.path.join(tmp, "t.db")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def run(llm, settings, lineup=None):
    repo = Repository(settings.db_path)
    d = repo.create_debate(TOPIC, lineup or make_lineup())
    orch = Orchestrator(d, repo, llm=llm, settings=settings)

    async def collect():
        evs = []
        async for ev in orch.run():
            evs.append(ev)
        return evs, repo

    evs, repo = asyncio.run(collect())
    return evs, repo, d


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_converges_and_persists(self):
        s = make_settings(self.tmp, max_rounds=2, max_speeches_per_round=3)
        evs, repo, d = run(MockLLMClient(s, chunk_delay=0.001, think_delay=0.01), s)
        self.assertIn("done", [e["event"] for e in evs])
        self.assertEqual(repo.get_debate(d.id).status, "done")
        self.assertGreaterEqual(len(repo.list_messages(d.id)), 4)
        rounds = [e["data"]["round"] for e in evs if e["event"] == "round_change"]
        self.assertLessEqual(max(rounds), s.max_rounds)

    def test_no_consecutive_same_speaker(self):
        """需求红线：不允许机械式轮流发言，连续同一人更要避免。"""
        s = make_settings(self.tmp, max_rounds=2, max_speeches_per_round=3)
        evs, _, _ = run(MockLLMClient(s, chunk_delay=0.001, think_delay=0.01), s)
        order = [e["data"]["speaker"] for e in evs
                 if e["event"] == "speaker_start" and e["data"]["speaker"] != "host"]
        self.assertGreater(len(order), 2)
        for a, b in zip(order, order[1:]):
            self.assertNotEqual(a, b)

    def test_agent_status_events_emitted(self):
        s = make_settings(self.tmp, max_rounds=1, max_speeches_per_round=2)
        evs, _, _ = run(MockLLMClient(s, chunk_delay=0.001, think_delay=0.01), s)
        status_evs = [e for e in evs if e["event"] == "agent_status"]
        self.assertTrue(status_evs)
        kinds = {e["data"]["status"] for e in status_evs}
        self.assertTrue({"preparing", "speaking", "standby"} & kinds)
        self.assertTrue(all(e["data"].get("thought") for e in status_evs))

    def test_insight_updates_during_discussion(self):
        s = make_settings(self.tmp, max_rounds=2, max_speeches_per_round=3)
        evs, repo, d = run(MockLLMClient(s, chunk_delay=0.001, think_delay=0.01), s)
        insight_evs = [e for e in evs if e["event"] == "insight"]
        self.assertTrue(insight_evs, "应在讨论过程中产出共识/分歧")
        first_idx = next(i for i, e in enumerate(evs) if e["event"] == "insight")
        self.assertLess(first_idx, len(evs) - 1)
        self.assertTrue(repo.get_debate(d.id).consensus or repo.get_debate(d.id).disagreements)

    def test_speech_is_short(self):
        s = make_settings(self.tmp, max_rounds=1, max_speeches_per_round=2)
        _, repo, d = run(MockLLMClient(s, chunk_delay=0.001, think_delay=0.01), s)
        for m in repo.list_messages(d.id):
            if m.role == "guest":
                self.assertLessEqual(len(m.content), 160)


class TestContext(unittest.TestCase):
    def test_history_clipped(self):
        msgs = [Message(debate_id="x", round=1, speaker_id="a", speaker_name="A",
                        role="guest", content="长内容" * 500) for _ in range(12)]
        self.assertLessEqual(len(visible_history(msgs, window=4, max_chars=2000)), 2200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
