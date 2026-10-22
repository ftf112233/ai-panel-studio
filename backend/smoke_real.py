"""真实 DeepSeek 联调脚本（会消耗 token，按需运行）。

    DEEPSEEK_API_KEY=sk-xxx python backend/smoke_real.py

默认跑 1 轮 / 2 次发言，只为验证链路可用，不做完整评估。
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agents.lineup import LineupAgent  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm.client import DeepSeekClient  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.storage.db import Repository  # noqa: E402

TOPIC = os.environ.get("REAL_TOPIC", "AI 编程工具会取代初级程序员吗？")


async def main():
    if not settings.deepseek_api_key:
        print("未设置 DEEPSEEK_API_KEY，退出")
        return
    settings.db_path = os.path.join(tempfile.mkdtemp(), "real.db")
    settings.max_rounds = int(os.environ.get("REAL_ROUNDS", "1"))
    settings.max_speeches_per_round = int(os.environ.get("REAL_SPEECHES", "2"))

    repo = Repository(settings.db_path)
    llm = DeepSeekClient(settings)

    print("→ 阵容生成（真实模型）")
    lineup = await LineupAgent(llm).generate(TOPIC, 4)
    for e in lineup.experts:
        print(f"   {e.name}｜{e.occupation}/{e.title}｜{e.stance[:30]}")

    d = repo.create_debate(TOPIC, lineup)
    orch = Orchestrator(d, repo, llm=llm, settings=settings)
    print("\n→ 讨论进行中（真实流式）")
    async for ev in orch.run():
        if ev["event"] == "speaker_start" and ev["data"]["speaker"] != "host":
            print(f"   [{ev['data'].get('action_label')}] {ev['data']['name']}（{ev['data'].get('title')}）")
        elif ev["event"] == "speaker_end" and ev["data"]["speaker"] == "host":
            print("")
        elif ev["event"] == "insight":
            print(f"   共识 {len(ev['data']['consensus'])} 条 / 分歧 {len(ev['data']['disagreements'])} 条")
        elif ev["event"] == "done":
            print("\n→ 总结：", ev["data"]["summary"])
        elif ev["event"] == "error":
            print("!! ", ev["data"]["message"])

    print("\n落库发言：", len(repo.list_messages(d.id)), "| 状态：", repo.get_debate(d.id).status)


if __name__ == "__main__":
    asyncio.run(main())
