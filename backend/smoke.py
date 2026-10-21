"""零依赖冒烟：用 Mock 客户端跑完整圆桌，验证编排链路与 SSE 事件序列化。

不装 fastapi 也能跑：
    python backend/smoke.py
"""
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import Settings  # noqa: E402
from app.llm.client import MockLLMClient  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.storage.db import Repository, SEED_PERSONAS  # noqa: E402


async def main():
    tmp = tempfile.mkdtemp()
    s = Settings()
    s.db_path = os.path.join(tmp, "smoke.db")
    s.max_rounds = 2
    s.max_speeches_per_round = 2

    repo = Repository(s.db_path)
    personas = [p for p in SEED_PERSONAS if p.id in {"optimist", "skeptic", "builder"}]
    d = repo.create_debate("AI 编程工具会取代初级程序员吗？", [p.id for p in personas])

    orch = Orchestrator(d, personas, repo, llm=MockLLMClient(s), settings=s)
    counts: dict[str, int] = {}
    async for ev in orch.run():
        counts[ev["event"]] = counts.get(ev["event"], 0) + 1
        # 验证可被 JSON 序列化（SSE 传输前提）
        json.dumps(ev, ensure_ascii=False)
        if ev["event"] in {"participants", "round_change", "error"}:
            print(f"[{ev['event']}] {ev['data']}")

    print("\n事件统计:", counts)
    print("圆桌状态:", repo.get_debate(d.id).status)
    print("落库发言:", len(repo.list_messages(d.id)))
    print("总结:", repo.get_debate(d.id).summary[:80])


if __name__ == "__main__":
    asyncio.run(main())
