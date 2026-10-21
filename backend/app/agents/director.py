"""发言调度 Agent：决定「下一句谁来说、以什么动作来说」。

需求对应：专家根据 transcript 自主决定发言顺序（举手/抢答/补充/反驳），
不允许机械式轮流发言；同时产出可公开的「思考摘要」给状态小窗（不是隐藏 CoT）。

校验与降级：
- speaker 必须是在座专家，且不能与上一位相同；
- 非法则由调度器按「本轮未发言优先 + 上次发言最早」的确定性规则补位；
- thought 缺失时给一句通用摘要，绝不把 JSON 原文推给前端。
"""
from __future__ import annotations

from ..llm.client import BaseLLMClient
from ..storage.db import Expert
from .base import BaseAgent, load_prompt

DIRECTOR_PROMPT = "director.v1.json"

ACTION_LABEL = {
    "raise_hand": "举手",
    "supplement": "补充",
    "rebut": "反驳",
}


class DirectorAgent(BaseAgent):
    def __init__(self, llm: BaseLLMClient, topic: str, experts: list[Expert]):
        super().__init__(llm, name="调度器", speaker_id="director")
        self.topic = topic
        self.experts = experts
        self.prompt = load_prompt(DIRECTOR_PROMPT)
        self.spoken_count: dict[str, int] = {e.id: 0 for e in experts}

    def _brief(self) -> str:
        return "\n".join(
            f"- {e.id}｜{e.name}（{e.occupation}/{e.title}）：{e.stance}" for e in self.experts
        )

    async def pick(self, focus: str, recent_digest: str, last_speaker: str | None) -> dict:
        messages = [
            {"role": "system", "content": self.prompt["system"]},
            {"role": "user", "content": self._fmt(
                self.prompt["user"], topic=self.topic, focus=focus,
                last_speaker=last_speaker or "（尚未有人发言）",
                experts_brief=self._brief(), recent_digest=recent_digest or "（暂无）")},
        ]
        obj = await self._call_json(messages, retries=1, temperature=0.9)
        return self._normalize(obj, last_speaker, focus)

    def _normalize(self, obj: dict | None, last_speaker: str | None, focus: str) -> dict:
        valid = {e.id for e in self.experts}
        speaker = (obj or {}).get("speaker")
        action = str((obj or {}).get("action") or "raise_hand").lower()
        if action not in ACTION_LABEL:
            action = "raise_hand"
        thought = str((obj or {}).get("thought") or "").strip()

        if speaker not in valid or speaker == last_speaker:
            speaker = self._fallback_speaker(last_speaker)
            if not thought:
                thought = f"想就「{focus[:18]}」补一个自己的角度"
        if not thought:
            thought = "刚被点到，想把自己的判断说清楚"

        self.spoken_count[speaker] = self.spoken_count.get(speaker, 0) + 1
        return {"speaker": speaker, "action": action, "thought": thought}

    def _fallback_speaker(self, last_speaker: str | None) -> str:
        """确定性补位：本轮发言次数最少者优先，且排除上一位。"""
        candidates = [e for e in self.experts if e.id != last_speaker] or self.experts
        return min(candidates, key=lambda e: self.spoken_count.get(e.id, 0)).id
