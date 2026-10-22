"""共识 / 分歧提炼 Agent：每条发言后增量更新（需求：不等到结束才生成）。

去重策略：归一化文本（去标点空白）后比对，已存在则跳过；分歧按 (a,b,point) 三元组比对。
上限控制：共识 6 条、分歧 6 条，超出丢弃最早的，保证 UI 区域不膨胀。
"""
from __future__ import annotations

import re

from ..llm.client import BaseLLMClient
from .base import BaseAgent, load_prompt

INSIGHT_PROMPT = "insight.v1.json"

MAX_CONSENSUS = 6
MAX_DISAGREEMENTS = 6


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


class InsightAgent(BaseAgent):
    def __init__(self, llm: BaseLLMClient, topic: str):
        super().__init__(llm, name="议题分析员", speaker_id="insight")
        self.topic = topic
        self.prompt = load_prompt(INSIGHT_PROMPT)

    async def extract(self, consensus: list[str], disagreements: list[dict], latest: str,
                      speaker: str = "") -> dict:
        messages = [
            {"role": "system", "content": self.prompt["system"]},
            {"role": "user", "content": self._fmt(
                self.prompt["user"], topic=self.topic,
                consensus="\n".join(f"- {c}" for c in consensus) or "（暂无）",
                disagreements="\n".join(f"- {d.get('a','')} vs {d.get('b','')}：{d.get('point','')}"
                                        for d in disagreements) or "（暂无）",
                speaker=speaker or "（未知）", latest=latest or "（暂无）")},
        ]
        obj = await self._call_json(messages, retries=0, temperature=0.3)
        return merge_insights(consensus, disagreements, obj or {})


def merge_insights(consensus: list[str], disagreements: list[dict], new: dict) -> dict:
    """把新提炼结果并入已有列表（纯函数，便于单测）。"""
    out_c = list(consensus)
    out_d = list(disagreements)

    for text in (new.get("consensus") or []):
        if not isinstance(text, str) or len(text.strip()) < 3:  # 中文 3 字即可成句
            continue
        text = text.strip()
        if all(_norm(text) != _norm(x) for x in out_c):
            out_c.append(text)
    out_c = out_c[-MAX_CONSENSUS:]

    for d in (new.get("disagreements") or []):
        if not isinstance(d, dict):
            continue
        item = {
            "a": str(d.get("a") or "").strip(),
            "b": str(d.get("b") or "").strip(),
            "point": str(d.get("point") or "").strip(),
        }
        if not item["a"] or not item["b"] or len(item["point"]) < 3:
            continue
        if all(not (_norm(item["a"]) == _norm(x["a"]) and _norm(item["b"]) == _norm(x["b"])
                    and _norm(item["point"]) == _norm(x["point"])) for x in out_d):
            out_d.append(item)
    out_d = out_d[-MAX_DISAGREEMENTS:]

    return {"consensus": out_c, "disagreements": out_d}
