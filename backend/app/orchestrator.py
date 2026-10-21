"""圆桌编排器（作业核心考察点：发言调度）。

状态机：
    CREATED → OPENING → ROUND[1..N] → SUMMARY → DONE

每轮流程：
    主持人（开场/串联/追问）→ 调度器根据 transcript 选人（举手/抢答/补充/反驳）
    → 专家 1-2 句发言（流式）→ 共识/分歧增量提炼 → 主持人串联 …
    → 主持人可插话打断过长的发言

状态小窗事件：agent_status {speaker_id, status: standby|preparing|speaking, thought}
其中 thought 是**可公开**的思考摘要，绝不输出隐藏 chain-of-thought。

兜底：任一环节失败都不中断直播（详见 README 兜底表）。
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .agents.director import ACTION_LABEL, DirectorAgent
from .agents.guest import GuestAgent, chunk_text
from .agents.host import HostAgent
from .agents.insight import InsightAgent
from .config import Settings, settings as global_settings
from .context import recent_digest, visible_history
from .llm.client import BaseLLMClient, build_client
from .storage.db import Debate, Message, Repository


def _ev(event: str, **data) -> dict:
    return {"event": event, "data": data}


class Orchestrator:
    def __init__(self, debate: Debate, repo: Repository, llm: BaseLLMClient | None = None,
                 settings: Settings | None = None):
        self.debate = debate
        self.repo = repo
        self.settings = settings or global_settings
        self.llm = llm or build_client(self.settings)

        self.experts = debate.lineup.experts
        self.expert_map = {e.id: e for e in self.experts}
        self.host = HostAgent(self.llm, debate.topic, self.experts,
                              host_name=debate.lineup.host_name,
                              host_title=debate.lineup.host_title)
        self.director = DirectorAgent(self.llm, debate.topic, self.experts)
        self.insight = InsightAgent(self.llm, debate.topic)
        self.guests = {e.id: GuestAgent(self.llm, e) for e in self.experts}

        self.messages: list[Message] = []
        self.focus: str = debate.topic
        self.consensus: list[str] = list(debate.consensus)
        self.disagreements: list[dict] = list(debate.disagreements)
        self.last_speaker: str | None = None
        self.host_chunk_delay = 0.02
        self.interrupt_chars = 120      # 单条发言超过该字数，主持人插话

    # ---------------------------------------------------------------- 主流程
    async def run(self) -> AsyncIterator[dict]:
        self.repo.update_debate(self.debate.id, status="running")
        yield _ev("participants", debate_id=self.debate.id, topic=self.debate.topic,
                  host={"id": "host", "name": self.host.name, "title": self.host.host_title,
                        "avatar": self.host.name[:1], "color": "#495057"},
                  guests=[{"id": e.id, "name": e.name, "occupation": e.occupation,
                           "title": e.title, "stance": e.stance, "avatar": e.avatar,
                           "color": e.color} for e in self.experts])

        try:
            round_no = 1
            self.repo.update_debate(self.debate.id, round=round_no)
            yield _ev("round_change", round=round_no, focus=self.focus)

            # ---------------- 开场 ----------------
            opening = await self.host.opening()
            async for ev in self._emit_host(opening, round_no):
                yield ev
            if opening.get("focus"):
                self.focus = opening["focus"]
                yield _ev("focus", focus=self.focus)

            # ---------------- 轮次循环 ----------------
            while round_no <= self.settings.max_rounds:
                speeches = 0
                while speeches < self.settings.max_speeches_per_round:
                    async for ev in self._expert_turn(round_no):
                        yield ev
                    speeches += 1

                    if speeches >= self.settings.max_speeches_per_round:
                        break

                    last = self.messages[-1] if self.messages else None
                    d = await self.host.transition(
                        round_no=round_no, max_rounds=self.settings.max_rounds, speeches=speeches,
                        action=(last.meta.get("action_label") if last else ""),
                        last_speaker=(last.speaker_name if last else ""),
                        last_content=(last.content if last else ""))
                    if d["type"] == "summary":
                        round_no = self.settings.max_rounds + 1
                        break
                    async for ev in self._emit_host(d, round_no):
                        yield ev
                    if d.get("focus"):
                        self.focus = d["focus"]
                        yield _ev("focus", focus=self.focus)

                if round_no >= self.settings.max_rounds:
                    break
                round_no += 1
                self.repo.update_debate(self.debate.id, round=round_no)
                yield _ev("round_change", round=round_no, focus=self.focus)

            # ---------------- 总结 ----------------
            yield _ev("agent_status", speaker_id="host", status="preparing",
                      thought="准备收束全场，点出真正的分歧点")
            summary = await self.host.summary()
            async for ev in self._emit_host(summary, round_no):
                yield ev
            self.repo.update_debate(
                self.debate.id, status="done", round=round_no, summary=summary["content"],
                consensus=self.consensus, disagreements=self.disagreements)
            yield _ev("done", debate_id=self.debate.id, summary=summary["content"])

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.repo.update_debate(self.debate.id, status="failed")
            yield _ev("error", message=f"圆桌中断：{type(e).__name__}: {e}", recoverable=True)

    # ---------------------------------------------------------------- 子流程
    async def _expert_turn(self, round_no: int) -> AsyncIterator[dict]:
        """一次专家发言：调度器选人 → 状态小窗 → 流式发言 → 插话 → 共识提炼。"""
        # 1. 调度：自主决定下一位（禁止机械轮流）
        pick = await self.director.pick(
            focus=self.focus,
            recent_digest=recent_digest(self.messages, self.settings.history_window),
            last_speaker=self.last_speaker)
        speaker_id, action = pick["speaker"], pick["action"]
        expert = self.expert_map[speaker_id]
        guest = self.guests[speaker_id]

        # 2. 状态小窗：被点名者「准备发言」+ 公开思考摘要（非 CoT）
        yield _ev("agent_status", speaker_id=speaker_id, status="preparing", thought=pick["thought"])
        yield _ev("agent_status", speaker_id=speaker_id, status="speaking",
                  thought=f"关注：{self.focus[:24]}")

        # 3. 流式发言（1-2 句）
        last_line = self.messages[-1].content if self.messages else ""
        history = visible_history(self.messages, self.settings.history_window,
                                  self.settings.max_history_chars)
        yield _ev("speaker_start", speaker=speaker_id, name=expert.name,
                  occupation=expert.occupation, title=expert.title, color=expert.color,
                  action=action, action_label=ACTION_LABEL.get(action, "发言"))
        buf: list[str] = []
        interrupted = False
        async for delta in guest.speak(self.debate.topic, self.focus, action, last_line, history):
            buf.append(delta)
            yield _ev("delta", speaker=speaker_id, text=delta)
            if sum(len(x) for x in buf) > self.interrupt_chars:
                interrupted = True
                break
        content = "".join(buf).strip()
        yield _ev("speaker_end", speaker=speaker_id, interrupted=interrupted)
        yield _ev("agent_status", speaker_id=speaker_id, status="standby",
                  thought=(f"刚说完：{content[:20]}…" if content else "待机中"))

        # 4. 主持人插话：发言过长则打断并要求给结论
        if interrupted:
            yield _ev("agent_status", speaker_id="host", status="speaking", thought="这段太长了，插话")
            inter = await self.host.interrupt(expert.name, len(content))
            async for ev in self._emit_host(inter, round_no, interrupt=True):
                yield ev
            yield _ev("agent_status", speaker_id=speaker_id, status="speaking", thought="补一句结论")
            tail = ""
            async for delta in guest.speak(self.debate.topic, "请用一句话给出结论或代价数字",
                                           "raise_hand", content, ""):
                tail += delta
                yield _ev("delta", speaker=speaker_id, text=delta)
            yield _ev("speaker_end", speaker=speaker_id, interrupted=False)
            yield _ev("agent_status", speaker_id=speaker_id, status="standby", thought="已给出结论")
            content = (content + " " + tail).strip()

        # 5. 落库 + 立场漂移
        shift = "hold"
        if content:
            try:
                shift = await guest.stance_shift(content)
            except Exception:
                shift = "hold"
        m = Message(debate_id=self.debate.id, round=round_no, speaker_id=speaker_id,
                    speaker_name=expert.name, role="guest", content=content,
                    meta={"action": action, "action_label": ACTION_LABEL.get(action, "发言"),
                          "stance_shift": shift, "focus": self.focus, "interrupted": interrupted})
        self.messages.append(m)
        self.repo.add_message(m)
        self.last_speaker = speaker_id
        yield _ev("stance", speaker=speaker_id, name=expert.name, shift=shift)

        # 6. 共识 / 分歧增量提炼（实时，不等结束）
        try:
            merged = await self.insight.extract(self.consensus, self.disagreements, content)
        except Exception:
            merged = {"consensus": self.consensus, "disagreements": self.disagreements}
        if merged["consensus"] != self.consensus or merged["disagreements"] != self.disagreements:
            self.consensus, self.disagreements = merged["consensus"], merged["disagreements"]
            self.repo.update_debate(self.debate.id, consensus=self.consensus,
                                    disagreements=self.disagreements)
            yield _ev("insight", consensus=self.consensus, disagreements=self.disagreements)

    async def _emit_host(self, d: dict, round_no: int, interrupt: bool = False) -> AsyncIterator[dict]:
        yield _ev("speaker_start", speaker="host", name=self.host.name, title=self.host.host_title,
                  color="#495057", type=d.get("type"), interrupt=interrupt,
                  degraded=bool(d.get("degraded")))
        for seg in chunk_text(d["content"], size=2):
            await asyncio.sleep(self.host_chunk_delay)
            yield _ev("delta", speaker="host", text=seg)
        yield _ev("speaker_end", speaker="host")

        m = Message(debate_id=self.debate.id, round=round_no, speaker_id="host",
                    speaker_name=self.host.name, role="host", content=d["content"],
                    meta={"type": d.get("type"), "focus": d.get("focus", ""), "interrupt": interrupt})
        self.messages.append(m)
        self.repo.add_message(m)
