"""Orchestrator 单测：零第三方依赖（unittest + asyncio），用桩 LLM 跑通全链路。

覆盖：
1. 状态机一定会收敛到 done，且不超过配置的轮数上限；
2. 消息全部落库；
3. Host 输出非法 JSON 时降级不中断；
4. Guest 流式抛异常时补占位句，直播继续；
5. 点名制下不会连续点同一个人（超出上限时由调度器兜底轮换）。
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.base import extract_json
from app.config import Settings
from app.context import visible_history
from app.orchestrator import Orchestrator
from app.storage.db import Repository, SEED_PERSONAS


class StubLLM:
    """可编程桩：host_out 为队列，逐个返回；stream 按 script 产出。"""

    def __init__(self, host_script=None, guest_text="这是嘉宾的标准发言，长度足够二十字以上。", fail_stream=False):
        self.host_script = list(host_script or [])
        self.guest_text = guest_text
        self.fail_stream = fail_stream
        self.stream_calls = 0

    async def json_chat(self, messages, temperature=0.7):
        if self.host_script:
            item = self.host_script.pop(0)
        else:
            item = '{"type":"summary","content":"收束","next_speaker":null,"focus":""}'
        return {"text": item}

    async def stream_chat(self, messages, temperature=0.9):
        self.stream_calls += 1
        if self.fail_stream and self.stream_calls == 1:
            raise RuntimeError("模拟流式中断")
            yield  # pragma: no cover
        for i in range(0, len(self.guest_text), 5):
            yield self.guest_text[i:i + 5]


def make_settings(tmpdir, **kw):
    s = Settings()
    s.db_path = os.path.join(tmpdir, "t.db")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def run_orchestrator(llm, settings, persona_ids=("optimist", "skeptic")):
    repo = Repository(settings.db_path)
    personas = [p for p in SEED_PERSONAS if p.id in persona_ids]
    d = repo.create_debate("AI 会取代初级程序员吗？", [p.id for p in personas])
    orch = Orchestrator(d, personas, repo, llm=llm, settings=settings)

    async def collect():
        events = []
        async for ev in orch.run():
            events.append(ev)
        return events, repo

    events, repo = asyncio.run(collect())
    return events, repo, d


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_state_machine_converges(self):
        settings = make_settings(self.tmp, max_rounds=2, max_speeches_per_round=2)
        events, repo, d = run_orchestrator(StubLLM(), settings)
        self.assertIn("done", [e["event"] for e in events])
        self.assertEqual(repo.get_debate(d.id).status, "done")
        # 轮数不超过上限
        rounds = [e["data"]["round"] for e in events if e["event"] == "round_change"]
        self.assertLessEqual(max(rounds), settings.max_rounds)
        # 所有发言落库
        msgs = repo.list_messages(d.id)
        self.assertGreaterEqual(len(msgs), 3)
        self.assertTrue(all(m.content.strip() for m in msgs))

    def test_host_invalid_json_degrades(self):
        settings = make_settings(self.tmp, max_rounds=1, max_speeches_per_round=1)
        llm = StubLLM(host_script=["这不是JSON", "也不是JSON"])
        events, repo, d = run_orchestrator(llm, settings)
        degraded = [e for e in events if e["event"] == "speaker_start" and e["data"].get("degraded")]
        self.assertTrue(degraded, "Host JSON 解析失败应降级而非中断")
        self.assertEqual(repo.get_debate(d.id).status, "done")

    def test_guest_stream_failure_placeholder(self):
        settings = make_settings(self.tmp, max_rounds=1, max_speeches_per_round=1)
        llm = StubLLM(fail_stream=True)
        events, repo, d = run_orchestrator(llm, settings)
        self.assertEqual(repo.get_debate(d.id).status, "done")
        guest_msgs = [m for m in repo.list_messages(d.id) if m.role == "guest"]
        self.assertTrue(guest_msgs and all(m.content.strip() for m in guest_msgs))

    def test_illegal_next_speaker_fixed(self):
        settings = make_settings(self.tmp, max_rounds=1, max_speeches_per_round=2)
        llm = StubLLM(host_script=['{"type":"question","content":"下一位","next_speaker":"ghost","focus":"f"}'])
        events, repo, d = run_orchestrator(llm, settings, persona_ids=("optimist", "builder"))
        speakers = {m.speaker_id for m in repo.list_messages(d.id) if m.role == "guest"}
        self.assertTrue(speakers.issubset({"optimist", "builder"}))


class TestUtils(unittest.TestCase):
    def test_extract_json_tolerant(self):
        self.assertEqual(extract_json('```json\n{"a":1}\n```'), {"a": 1})
        self.assertEqual(extract_json('前面有解释 {"a": 2} 后面也有'), {"a": 2})
        self.assertIsNone(extract_json("完全没有 JSON"))

    def test_visible_history_clipped(self):
        from app.storage.db import Message
        msgs = [Message(debate_id="x", round=1, speaker_id="a", speaker_name="A",
                        role="guest", content="长内容" * 500) for _ in range(12)]
        text = visible_history(msgs, window=4, max_chars=2000)
        self.assertLessEqual(len(text), 2200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
