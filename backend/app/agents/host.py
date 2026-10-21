"""主持人 Agent：开场 / 追问 / 串联 / 插话 / 总结。

对齐需求：主持人负责开场、追问、串联和总结；每次 1-2 句；插话用于打断跑题的长发言。
输出为决策 JSON（type / content / focus），由 Orchestrator 校验后再推给前端，
页面上永远只出现 content 这一句自然语言（禁止显示 JSON 原文）。
"""
from __future__ import annotations

from ..llm.client import BaseLLMClient
from ..storage.db import Expert
from .base import BaseAgent, load_prompt

HOST_PROMPT = "host.v5.json"

VALID_TYPES = {"opening", "question", "transition", "interrupt", "summary"}


class HostAgent(BaseAgent):
    def __init__(self, llm: BaseLLMClient, topic: str, experts: list[Expert],
                 host_name: str = "知遥", host_title: str = "主持人"):
        super().__init__(llm, name=host_name, speaker_id="host")
        self.topic = topic
        self.experts = experts
        self.host_title = host_title
        self.prompt = load_prompt(HOST_PROMPT)
        self.system = self._fmt(
            self.prompt["system"],
            host_name=host_name, topic=topic,
            experts_brief="\n".join(
                f"- {e.id}｜{e.name}（{e.occupation}/{e.title}）：{e.stance}" for e in experts),
        )

    def _messages(self, user_text: str) -> list[dict]:
        return [{"role": "system", "content": self.system}, {"role": "user", "content": user_text}]

    async def opening(self) -> dict:
        return await self._decide(self.prompt["opening_user"], "opening")

    async def transition(self, *, round_no: int, max_rounds: int, speeches: int, action: str,
                         last_speaker: str, last_content: str) -> dict:
        user = self._fmt(self.prompt["next_user"], round=round_no, max_rounds=max_rounds,
                         speeches=speeches, action=action or "发言",
                         last_speaker=last_speaker or "（无人）",
                         last_content=(last_content or "")[:120])
        return await self._decide(user, "transition")

    async def interrupt(self, name: str, chars: int) -> dict:
        user = self._fmt(self.prompt["interrupt_user"], name=name, chars=chars)
        return await self._decide(user, "interrupt")

    async def summary(self) -> dict:
        return await self._decide(self.prompt["summary_user"], "summary")

    async def _decide(self, user: str, stage: str) -> dict:
        obj = await self._call_json(self._messages(user), retries=1, temperature=0.8)
        return self._normalize(obj, stage)

    def _normalize(self, obj: dict | None, stage: str) -> dict:
        t = str((obj or {}).get("type") or stage).strip().lower()
        if t not in VALID_TYPES:
            t = stage if stage in VALID_TYPES else "transition"
        content = str((obj or {}).get("content") or "").strip()
        focus = str((obj or {}).get("focus") or "").strip()
        if not content:
            content, focus = self._fallback(stage), self.topic
        return {"type": t, "content": content, "focus": focus or self.topic,
                "degraded": obj is None}

    def _fallback(self, stage: str) -> str:
        if stage == "opening":
            return f"今天我们聊「{self.topic}」，在座几位立场差得挺远，我们直接开场。"
        if stage == "summary":
            return (f"关于「{self.topic}」，今天没有统一结论，但分歧已经很具体："
                    f"风险和收益的先后顺序，才是真正要决策的东西。")
        if stage == "interrupt":
            return "我先插一句——请直接给结论，别再铺背景了。"
        return "刚才这个说法我想再往下追一层，换个角度看会不会不一样？"
