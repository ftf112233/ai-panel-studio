"""SQLite 持久层（标准库 sqlite3，零运维）。

三张表：personas（嘉宾人设）/ debates（圆桌）/ messages（发言流水）。
所有写操作都在这里，Orchestrator 只面向 Repository 接口，方便单测替换。
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Persona:
    id: str
    name: str
    title: str
    background: str
    stance: str
    style: str
    avatar: str
    color: str
    disagreement_with: list[str] = field(default_factory=list)
    version: str = "v3"


@dataclass
class Message:
    debate_id: str
    round: int
    speaker_id: str
    speaker_name: str
    role: str          # host | guest
    content: str
    meta: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=_now)


@dataclass
class Debate:
    id: str
    topic: str
    persona_ids: list[str]
    status: str            # created | running | done | failed
    created_at: str = field(default_factory=_now)
    round: int = 0
    summary: str = ""


# --------------------------------------------------------------------------
# 人设种子数据（v3：预埋结构性分歧，见 docs/02-Prompt设计文档.md）
# --------------------------------------------------------------------------
SEED_PERSONAS: list[Persona] = [
    Persona(
        id="optimist",
        name="林一舟",
        title="技术乐观派",
        background="AI 产品创业者，连续做过两个 AI 应用，融资到 A 轮",
        stance="AI 原生应用会在两年内取代大部分传统软件交互，先上船的人吃红利",
        style="语速快、爱用类比、会直接点名反驳",
        avatar="林",
        color="#e8590c",
        disagreement_with=["skeptic"],
    ),
    Persona(
        id="skeptic",
        name="沈观澜",
        title="落地怀疑派",
        background="传统行业 CTO，主导过 3 次 AI 落地项目，其中两次烂尾",
        stance="大模型落地卡在数据、成本和组织协同上，不是模型不够强",
        style="慎重、爱用数据泼冷水、常说「我给你算笔账」",
        avatar="沈",
        color="#1971c2",
        disagreement_with=["optimist"],
    ),
    Persona(
        id="builder",
        name="江野",
        title="一线工程派",
        background="大模型应用工程师，每天写 Prompt、做评测、调推理成本",
        stance="不站队，只关心具体怎么做得到，会把双方说法拆成工程细节",
        style="务实、爱举自己踩坑的例子、讨厌空对空",
        avatar="江",
        color="#2f9e44",
        disagreement_with=[],
    ),
    Persona(
        id="ethicist",
        name="苏未",
        title="风险与伦理派",
        background="科技伦理研究员，参与过行业合规标准起草",
        stance="效率不是唯一指标，责任归属与用户知情权会决定这条路能走多远",
        style="温和但坚持、喜欢追问「出了事谁负责」",
        avatar="苏",
        color="#9c36b5",
        disagreement_with=["optimist"],
    ),
    Persona(
        id="user_advocate",
        name="陈也",
        title="普通用户代表",
        background="非技术背景的中小企业主，付费用过 6 款 AI 工具",
        stance="别谈趋势，我只关心它能不能替我省下真金白银的时间",
        style="大白话、爱举自己被 AI 坑过的例子",
        avatar="陈",
        color="#0c8599",
        disagreement_with=[],
    ),
]


class Repository:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _txn(self):
        """事务上下文：提交（或回滚）并保证连接关闭，避免连接泄漏。"""
        conn = self._conn()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._txn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS personas (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    title TEXT,
                    background TEXT,
                    stance TEXT,
                    style TEXT,
                    avatar TEXT,
                    color TEXT,
                    disagreement_with TEXT,
                    version TEXT
                );
                CREATE TABLE IF NOT EXISTS debates (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    persona_ids TEXT NOT NULL,
                    status TEXT NOT NULL,
                    round INTEGER DEFAULT 0,
                    summary TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    debate_id TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    speaker_id TEXT NOT NULL,
                    speaker_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_msg_debate ON messages(debate_id, id);
                """
            )
            for p in SEED_PERSONAS:
                conn.execute(
                    "INSERT OR REPLACE INTO personas VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        p.id, p.name, p.title, p.background, p.stance, p.style,
                        p.avatar, p.color, json.dumps(p.disagreement_with, ensure_ascii=False), p.version,
                    ),
                )

    # ---------------- personas ----------------
    def list_personas(self) -> list[Persona]:
        with self._txn() as conn:
            rows = conn.execute("SELECT * FROM personas").fetchall()
        return [self._row_to_persona(r) for r in rows]

    def get_personas(self, ids: list[str]) -> list[Persona]:
        all_p = {p.id: p for p in self.list_personas()}
        return [all_p[i] for i in ids if i in all_p]

    @staticmethod
    def _row_to_persona(r: sqlite3.Row) -> Persona:
        return Persona(
            id=r["id"], name=r["name"], title=r["title"], background=r["background"],
            stance=r["stance"], style=r["style"], avatar=r["avatar"], color=r["color"],
            disagreement_with=json.loads(r["disagreement_with"] or "[]"), version=r["version"],
        )

    # ---------------- debates ----------------
    def create_debate(self, topic: str, persona_ids: list[str]) -> Debate:
        d = Debate(id=uuid.uuid4().hex[:12], topic=topic, persona_ids=persona_ids, status="created")
        with self._txn() as conn:
            conn.execute(
                "INSERT INTO debates (id, topic, persona_ids, status, round, summary, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (d.id, d.topic, json.dumps(persona_ids, ensure_ascii=False), d.status, 0, "", d.created_at),
            )
        return d

    def get_debate(self, debate_id: str) -> Debate | None:
        with self._txn() as conn:
            r = conn.execute("SELECT * FROM debates WHERE id=?", (debate_id,)).fetchone()
        if not r:
            return None
        return Debate(
            id=r["id"], topic=r["topic"], persona_ids=json.loads(r["persona_ids"]),
            status=r["status"], round=r["round"], summary=r["summary"], created_at=r["created_at"],
        )

    def list_debates(self, limit: int = 50) -> list[Debate]:
        with self._txn() as conn:
            rows = conn.execute(
                "SELECT * FROM debates ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Debate(id=r["id"], topic=r["topic"], persona_ids=json.loads(r["persona_ids"]),
                   status=r["status"], round=r["round"], summary=r["summary"], created_at=r["created_at"])
            for r in rows
        ]

    def update_debate(self, debate_id: str, status: str | None = None, round: int | None = None,
                      summary: str | None = None) -> None:
        fields, values = [], []
        if status is not None:
            fields.append("status=?"); values.append(status)
        if round is not None:
            fields.append("round=?"); values.append(round)
        if summary is not None:
            fields.append("summary=?"); values.append(summary)
        if not fields:
            return
        values.append(debate_id)
        with self._txn() as conn:
            conn.execute(f"UPDATE debates SET {','.join(fields)} WHERE id=?", values)

    # ---------------- messages ----------------
    def add_message(self, m: Message) -> Message:
        with self._txn() as conn:
            conn.execute(
                "INSERT INTO messages (id, debate_id, round, speaker_id, speaker_name, role, content, meta, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (m.id, m.debate_id, m.round, m.speaker_id, m.speaker_name, m.role,
                 m.content, json.dumps(m.meta, ensure_ascii=False), m.created_at),
            )
        return m

    def list_messages(self, debate_id: str) -> list[Message]:
        with self._txn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE debate_id=? ORDER BY rowid", (debate_id,)
            ).fetchall()
        return [
            Message(id=r["id"], debate_id=r["debate_id"], round=r["round"], speaker_id=r["speaker_id"],
                    speaker_name=r["speaker_name"], role=r["role"], content=r["content"],
                    meta=json.loads(r["meta"] or "{}"), created_at=r["created_at"])
            for r in rows
        ]
