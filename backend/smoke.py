"""零依赖冒烟：用 Mock 客户端跑完整一场圆桌，验证编排链路与 SSE 事件序列化。

    python backend/smoke.py
"""
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agents.lineup import LineupAgent  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm.client import MockLLMClient  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.storage.db import Repository, SEED_TOPICS  # noqa: E402


async def main():
    tmp = tempfile.mkdtemp()
    s = Settings()
    s.db_path = os.path.join(tmp, "smoke.db")
    s.max_rounds = 2
    s.max_speeches_per_round = 3

    repo = Repository(s.db_path)
    llm = MockLLMClient(s)

    # 1) 阵容生成（确定性 Mock）
    lineup = await LineupAgent(llm).generate(SEED_TOPICS[0]["topic"], 4)
    print("阵容：", " / ".join(f"{e.name}({e.title})" for e in lineup.experts))

    # 2) 跑一场
    d = repo.create_debate(SEED_TOPICS[0]["topic"], lineup)
    orch = Orchestrator(d, repo, llm=llm, settings=s)
    counts: dict[str, int] = {}
    async for ev in orch.run():
        counts[ev["event"]] = counts.get(ev["event"], 0) + 1
        json.dumps(ev, ensure_ascii=False)  # 可被 SSE 序列化
        if ev["event"] in {"participants", "insight", "error"}:
            print(f"[{ev['event']}] {str(ev['data'])[:160]}")

    print("\n事件统计:", counts)
    print("状态:", repo.get_debate(d.id).status, "| 发言数:", len(repo.list_messages(d.id)))
    print("总结:", repo.get_debate(d.id).summary[:80])
    print("共识:", repo.get_debate(d.id).consensus)
    print("分歧:", repo.get_debate(d.id).disagreements)


if __name__ == "__main__":
    asyncio.run(main())
