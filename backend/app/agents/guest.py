"""嘉宾 Agent：流式发言 + 立场漂移标注。

为什么正文不用 JSON 模式：流式 + 结构化不可兼得（前端会看到原始 JSON）。
方案：正文纯流式输出给用户；发言结束后再用一次极短的 JSON 调用标注 stance_shift，
成本极低（几十 token），失败即降级为 hold，不影响直播。
"""
from __future__ import annotations

from typing import AsyncIterator

from ..llm.client import BaseLLMClient
from ..storage.db import Persona
from .base import BaseAgent, load_prompt

GUEST_PROMPT = "guest.v3.json"


class GuestAgent(BaseAgent):
    def __init__(self, llm: BaseLLMClient, persona: Persona):
        super().__init__(llm, name=persona.name, speaker_id=persona.id)
        self.persona = persona
        self.prompt = load_prompt(GUEST_PROMPT)
        self.system = self._fmt(
            self.prompt["system"],
            role_name=persona.name,
            role_title=persona.title,
            role_background=persona.background,
            stance=persona.stance,
            style=persona.style,
        )
        self.said: list[str] = []  # 自己的历史发言，用于去重约束

    def _user(self, topic: str, focus: str, visible_history: str) -> str:
        base = self._fmt(
            self.prompt["user"],
            topic=topic, focus=focus, visible_history=visible_history or "（暂无）",
        )
        if self.said:
            base += "\n\n你之前说过（不要重复）：\n- " + "\n- ".join(self.said[-2:])
        return base

    async def speak(self, topic: str, focus: str, visible_history: str) -> AsyncIterator[str]:
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self._user(topic, focus, visible_history)},
        ]
        buf: list[str] = []
        try:
            async for delta in self.llm.stream_chat(messages, temperature=0.9):
                buf.append(delta)
                yield delta
        except Exception:
            # 流式中断兜底：已产出的部分照常上屏，不足则用占位句补齐，直播不中断
            text = "".join(buf).strip()
            if len(text) < 20:
                fallback = f"（{self.name}的网络不太稳）我的看法没变：{self.persona.stance}"
                yield fallback[len(text):] if text else fallback
                buf.append(fallback[len(text):] if text else fallback)
        full = "".join(buf).strip()
        if full:
            self.said.append(full[-120:])

    async def stance_shift(self, content: str) -> str:
        """标注立场变化：hold / soften / change，失败降级 hold。"""
        messages = [
            {"role": "system", "content": self.prompt["stance_shift_system"]},
            {"role": "user", "content": self._fmt(
                self.prompt["stance_shift_user"], stance=self.persona.stance, content=content[:400]
            )},
        ]
        obj = await self._call_json(messages, retries=1, temperature=0.2)
        if not obj:
            return "hold"
        v = str(obj.get("stance_shift", "hold")).strip().lower()
        return v if v in {"hold", "soften", "change"} else "hold"


def chunk_text(text: str, size: int = 4) -> list[str]:
    """把已生成文本分块回放，用于 Host 决策内容的"伪流式"上屏。"""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]
