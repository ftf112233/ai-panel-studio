"""圆桌编排器（作业核心考察点）。

状态机：
    CREATED → OPENING → ROUND[1..N]（每轮最多 K 次发言）→ SUMMARY → DONE

调度策略：点名制（主持人先给聚焦问题并点名，被点名者发言）。
选择点名制而非自由抢话的理由与实验计划见 docs/02-Prompt设计文档.md §5-Q3。

兜底策略（任一环节失败都不中断直播）：
    - Host 决策 JSON 解析失败   → HostAgent 内部降级为兜底文案 + 调度器备选发言人
    - Guest 流式中断/超时       → 已产出部分上屏，不足 20 字时补占位句
    - 任一轮/全程 达上限        → 强制进入 SUMMARY
    - 顶层异常                  → status=failed + error 事件，前端提示可重连
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .agents.guest import GuestAgent, chunk_text
from .agents.host import HostAgent
from .config import Settings, settings as global_settings
from .context import recent_digest, visible_history
from .llm.client import BaseLLMClient, build_client
from .storage.db import Debate, Message, Persona, Repository


def _ev(event: str, **data) -> dict:
    return {"event": event, "data": data}


class Orchestrator:
    def __init__(self, debate: Debate, personas: list[Persona], repo: Repository,
                 llm: BaseLLMClient | None = None, settings: Settings | None = None):
        self.debate = debate
        self.personas = personas
        self.repo = repo
        self.settings = settings or global_settings
        self.llm = llm or build_client(self.settings)
        self.host = HostAgent(self.llm, debate.topic, personas)
        self.guests = {p.id: GuestAgent(self.llm, p) for p in personas}
        self.order = [p.id for p in personas]
        self.messages: list[Message] = []
        self.last_focus: str = debate.topic

    # ---------------------------------------------------------------- 主流程
    async def run(self) -> AsyncIterator[dict]:
        self.repo.update_debate(self.debate.id, status="running")
        yield _ev(
            "participants",
            debate_id=self.debate.id,
            topic=self.debate.topic,
            host={"id": "host", "name": self.host.name, "avatar": "知", "color": "#495057"},
            guests=[
                {"id": p.id, "name": p.name, "title": p.title, "avatar": p.avatar, "color": p.color}
                for p in self.personas
            ],
        )

        try:
            round_no = 1
            self.repo.update_debate(self.debate.id, round=round_no)
            yield _ev("round_change", round=round_no, focus=self.debate.topic)

            # ---- 开场 ----
            yield _ev("thinking", speaker="host", name=self.host.name)
            d = await self.host.decide(
                stage="opening", round_no=round_no, max_rounds=self.settings.max_rounds,
                speakers_this_round=[], last_focus="", recent_digest="",
                fallback_speaker=self.order[0],
            )
            for ev in self._emit_host(d, round_no):
                yield ev
            focus = d["focus"] or self.debate.topic
            speaker = d["next_speaker"] or self.order[0]

            # ---- 轮次循环 ----
            while round_no <= self.settings.max_rounds:
                speeches = 0
                while speeches < self.settings.max_speeches_per_round:
                    async for ev in self._guest_turn(speaker, round_no, focus):
                        yield ev
                    speeches += 1

                    if speeches >= self.settings.max_speeches_per_round:
                        break

                    d = await self.host.decide(
                        stage="next", round_no=round_no, max_rounds=self.settings.max_rounds,
                        speakers_this_round=[m.speaker_id for m in self.messages[-speeches:]],
                        last_focus=self.last_focus,
                        recent_digest=recent_digest(self.messages, self.settings.history_window),
                        fallback_speaker=self._next_cyclic(speaker),
                    )
                    if d["type"] in {"summary", "closing"}:
                        round_no = self.settings.max_rounds + 1  # 提前收束
                        break
                    for ev in self._emit_host(d, round_no):
                        yield ev
                    focus = d["focus"] or focus
                    speaker = d["next_speaker"] or self._next_cyclic(speaker)

                # 已达轮数上限（或主持人提前收束）→ 直接进入总结，不再开新轮
                if round_no >= self.settings.max_rounds:
                    break

                # ---- 进入下一轮：主持人给新聚焦问题 ----
                round_no += 1
                self.repo.update_debate(self.debate.id, round=round_no)
                yield _ev("round_change", round=round_no, focus=focus)
                d = await self.host.decide(
                    stage="next", round_no=round_no, max_rounds=self.settings.max_rounds,
                    speakers_this_round=[], last_focus=self.last_focus,
                    recent_digest=recent_digest(self.messages, self.settings.history_window),
                    fallback_speaker=self._next_cyclic(speaker),
                )
                if d["type"] in {"summary", "closing"}:
                    break
                for ev in self._emit_host(d, round_no):
                    yield ev
                focus = d["focus"] or focus
                speaker = d["next_speaker"] or self._next_cyclic(speaker)

            # ---- 总结 ----
            yield _ev("thinking", speaker="host", name=self.host.name)
            d = await self.host.decide(
                stage="summary", round_no=round_no, max_rounds=self.settings.max_rounds,
                speakers_this_round=[], last_focus=self.last_focus,
                recent_digest=recent_digest(self.messages, self.settings.history_window),
                fallback_speaker=None,
            )
            for ev in self._emit_host(d, round_no):
                yield ev
            self.repo.update_debate(self.debate.id, status="done", round=round_no, summary=d["content"])
            yield _ev("done", debate_id=self.debate.id, summary=d["content"])

        except asyncio.CancelledError:
            raise
        except Exception as e:  # 顶层兜底：不让直播页面挂掉
            self.repo.update_debate(self.debate.id, status="failed")
            yield _ev("error", message=f"圆桌中断：{type(e).__name__}: {e}", recoverable=True)

    # ---------------------------------------------------------------- 子流程
    async def _guest_turn(self, speaker_id: str, round_no: int, focus: str) -> AsyncIterator[dict]:
        guest = self.guests.get(speaker_id)
        if guest is None:  # 调度器拿到非法 ID 的极端情况
            guest = self.guests[self.order[0]]
        yield _ev("thinking", speaker=guest.speaker_id, name=guest.name)

        history = visible_history(self.messages, self.settings.history_window, self.settings.max_history_chars)
        yield _ev("speaker_start", speaker=guest.speaker_id, name=guest.name)
        buf: list[str] = []
        async for delta in guest.speak(self.debate.topic, focus, history):
            buf.append(delta)
            yield _ev("delta", speaker=guest.speaker_id, text=delta)
        content = "".join(buf).strip()
        yield _ev("speaker_end", speaker=guest.speaker_id)

        shift = "hold"
        if content:
            try:
                shift = await guest.stance_shift(content)
            except Exception:
                shift = "hold"

        m = Message(
            debate_id=self.debate.id, round=round_no, speaker_id=guest.speaker_id,
            speaker_name=guest.name, role="guest", content=content,
            meta={"stance_shift": shift, "focus": focus},
        )
        self.messages.append(m)
        self.repo.add_message(m)
        self.last_focus = focus
        yield _ev("stance", speaker=guest.speaker_id, name=guest.name, shift=shift)

    def _emit_host(self, d: dict, round_no: int) -> AsyncIterator[dict]:
        """主持人内容以"分块回放"上屏：决策已整体校验，观感仍是流式。"""
        yield _ev("speaker_start", speaker="host", name=self.host.name, degraded=bool(d.get("degraded")))
        for seg in chunk_text(d["content"], size=4):
            yield _ev("delta", speaker="host", text=seg)
        yield _ev("speaker_end", speaker="host")

        m = Message(
            debate_id=self.debate.id, round=round_no, speaker_id="host", speaker_name=self.host.name,
            role="host", content=d["content"], meta={"type": d["type"], "focus": d.get("focus", "")},
        )
        self.messages.append(m)
        self.repo.add_message(m)
        if d.get("focus"):
            yield _ev("focus", focus=d["focus"])

    def _next_cyclic(self, current: str) -> str:
        if current not in self.order:
            return self.order[0]
        i = self.order.index(current)
        return self.order[(i + 1) % len(self.order)]
