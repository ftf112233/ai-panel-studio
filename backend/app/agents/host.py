"""主持人 Agent：负责控场与调度决策。

输出为决策 JSON（type / content / next_speaker / focus）。
决策字段先整体校验，再以"分块回放"的方式把 content 流式推给前端——
这样既保证调度可靠，又保留流式观感（详见架构文档 §2.3）。
"""
from __future__ import annotations

from typing import Any

from ..llm.client import BaseLLMClient
from .base import BaseAgent, load_prompt

HOST_PROMPT = "host.v4.json"

VALID_TYPES = {"question", "transition", "summary", "closing"}


class HostAgent(BaseAgent):
    def __init__(self, llm: BaseLLMClient, topic: str, personas: list[Any]):
        super().__init__(llm, name="知遥", speaker_id="host")
        self.topic = topic
        self.personas = personas
        self.prompt = load_prompt(HOST_PROMPT)
        self.system = self._fmt(
            self.prompt["system"],
            topic=topic,
            personas_brief="\n".join(
                f"- {p.id}｜{p.name}（{p.title}）：{p.stance}" for p in personas
            ),
        )

    def _messages(self, user_text: str) -> list[dict]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": user_text},
        ]

    async def decide(self, *, stage: str, round_no: int, max_rounds: int,
                     speakers_this_round: list[str], last_focus: str,
                     recent_digest: str, fallback_speaker: str) -> dict:
        """返回规范化后的决策 dict，永不抛异常。"""
        if stage == "opening":
            user = self.prompt["opening_user"]
        elif stage == "summary":
            user = self.prompt["summary_user"]
        else:
            user = self._fmt(
                self.prompt["next_user"],
                round=round_no, max_rounds=max_rounds,
                speakers_this_round="、".join(speakers_this_round) or "（本轮尚未发言）",
                last_focus=last_focus or "（无）", recent_digest=recent_digest or "（无）",
            )

        obj = await self._call_json(self._messages(user), retries=1, temperature=0.7)
        return self._normalize(obj, stage, fallback_speaker, user)

    def _normalize(self, obj: dict | None, stage: str, fallback_speaker: str, raw_user: str) -> dict:
        """Schema 校验 + 降级：
        - 解析失败 -> 用兜底文案，type 按 stage 推断，next_speaker 用调度器给的备选；
        - next_speaker 不在在场嘉宾里 -> 修正为备选，避免调度器拿到非法 ID。
        """
        valid_ids = {p.id for p in self.personas}
        if obj is None:
            return {
                "type": "summary" if stage == "summary" else "question",
                "content": self._fallback_text(stage),
                "next_speaker": None if stage == "summary" else fallback_speaker,
                "focus": self.topic,
                "degraded": True,
            }
        t = str(obj.get("type", "question")).strip().lower()
        if t not in VALID_TYPES:
            t = "summary" if stage == "summary" else "question"
        nxt = obj.get("next_speaker")
        if nxt not in valid_ids:
            nxt = None if t in {"summary", "closing"} else fallback_speaker
        content = str(obj.get("content", "")).strip() or self._fallback_text(stage)
        focus = str(obj.get("focus", "")).strip() or self.topic
        return {"type": t, "content": content, "next_speaker": nxt, "focus": focus, "degraded": False}

    def _fallback_text(self, stage: str) -> str:
        if stage == "summary":
            return f"时间差不多了。关于「{self.topic}」，今天没有形成统一结论，但分歧点已经很清楚了。"
        if stage == "opening":
            return f"今天我们聊「{self.topic}」，在场几位立场差别不小，我们直接开始。"
        return "刚才这个说法我想再往下追一层，换个角度看看。"
