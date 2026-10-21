"""专家 Agent：1-2 句短发言（流式）+ 立场漂移标注。

正文不用 JSON 模式：流式与结构化不可兼得（前端会看到原始 JSON）。
方案：正文纯流式输出；发言结束后用一次极短 JSON 调用标注 stance_shift，
成本几十 token，失败即降级 hold，不影响直播。
"""
from __future__ import annotations

import hashlib

from typing import AsyncIterator

from ..llm.client import BaseLLMClient
from ..storage.db import Expert
from .base import BaseAgent, load_prompt

GUEST_PROMPT = "guest.v4.json"

ACTION_LABEL = {"raise_hand": "举手", "supplement": "补充", "rebut": "反驳"}


class GuestAgent(BaseAgent):
    def __init__(self, llm: BaseLLMClient, expert: Expert):
        super().__init__(llm, name=expert.name, speaker_id=expert.id)
        self.expert = expert
        self.prompt = load_prompt(GUEST_PROMPT)
        self.system = self._fmt(
            self.prompt["system"],
            role_name=expert.name,
            role_occupation=expert.occupation,
            role_title=expert.title,
            role_background=expert.background or expert.stance,
            stance=expert.stance,
            style=expert.style or "直接、讲具体例子",
        )
        self.said: list[str] = []

    def _user(self, topic: str, focus: str, action: str, last_line: str,
              visible_history: str) -> str:
        base = self._fmt(
            self.prompt["user"], topic=topic, focus=focus,
            action_label=ACTION_LABEL.get(action, "发言"),
            last_line=last_line or "（暂无）",
            visible_history=visible_history or "（暂无）",
        )
        if self.said:
            base += "\n\n你之前说过（不要重复）：\n- " + "\n- ".join(self.said[-2:])
        return base

    async def speak(self, topic: str, focus: str, action: str, last_line: str,
                    visible_history: str, max_chars: int = 120) -> AsyncIterator[str]:
        """流式发言。超过 max_chars 由调用方决定是否打断（主持人插话）。"""
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self._user(topic, focus, action, last_line, visible_history)},
        ]
        buf: list[str] = []
        try:
            async for delta in self.llm.stream_chat(messages, temperature=0.9):
                buf.append(delta)
                yield delta
        except Exception:
            text = "".join(buf).strip()
            if len(text) < 12:
                fallback = f"（{self.name}的网络不太稳）我的判断没变：{self.expert.stance}"
                yield fallback[len(text):] if text else fallback
                buf.append(fallback[len(text):] if text else fallback)
        full = "".join(buf).strip()
        if full:
            self.said.append(full[-100:])

    async def stance_shift(self, content: str) -> str:
        messages = [
            {"role": "system", "content": self.prompt["stance_shift_system"]},
            {"role": "user", "content": self._fmt(
                self.prompt["stance_shift_user"], stance=self.expert.stance, content=content[:400])},
        ]
        obj = await self._call_json(messages, retries=1, temperature=0.2)
        if not obj:
            return "hold"
        v = str(obj.get("stance_shift", "hold")).strip().lower()
        return v if v in {"hold", "soften", "change"} else "hold"


def chunk_text(text: str, size: int = 2) -> list[str]:
    """把已生成文本分块回放，用于主持人内容与历史回放的逐字上屏。"""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def mock_speech(expert_name: str, stance: str, topic: str, focus: str, seq: int) -> str:
    """Mock 客户端用的确定性短发言（1-2 句，40-90 字）。"""
    pool = [
        f"我的判断很直接：围绕{topic[:10]}，{stance[:14]}。",
        f"不同意刚才的说法，{focus[:12]}这一点上代价被低估了。",
        f"补一个我自己的例子：我们试点时真正卡住的是流程，不是模型能力。",
        f"我松动一点——你讲的成本我认，但节奏不能因此停下来。",
        f"结论先给：先小范围验证再铺开，别一步到位。",
        f"换个角度：真正决定成败的是谁能承担出错的责任。",
    ]
    h = int(hashlib.md5(f"{expert_name}{seq}".encode("utf-8")).hexdigest(), 16)
    return f"{expert_name}：" + pool[h % len(pool)]
