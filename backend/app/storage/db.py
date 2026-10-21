"""SQLite 持久层（标准库 sqlite3）。

实体（对应 PRD 数据建模 / docs/ER图.md）：
    topics     样例议题（≥5 条高质量种子数据：话题 + 预置阵容）
    debates    一场圆桌讨论（含动态生成的 lineup JSON、状态、共识/分歧 JSON）
    messages   发言流水（含发言动作：举手/抢答/补充/反驳，以及立场漂移）

隔离：每场讨论的 messages / 共识 / 分歧 均以 debate_id 为键，天然隔离。
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


PALETTE = ["#e8590c", "#1971c2", "#2f9e44", "#9c36b5", "#0c8599", "#e03131", "#fab005"]


@dataclass
class Expert:
    """嘉宾阵容中的一位专家（由大模型动态生成）。"""
    id: str
    name: str
    occupation: str
    title: str
    stance: str
    style: str = ""
    background: str = ""
    color: str = "#868e96"
    avatar: str = ""

    def __post_init__(self):
        if not self.avatar:
            self.avatar = self.name[:1]


@dataclass
class Lineup:
    """一场讨论的阵容：1 位主持人 + N 位专家。"""
    host_name: str = "知遥"
    host_title: str = "主持人"
    experts: list[Expert] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "host": {"name": self.host_name, "title": self.host_title},
            "experts": [vars(e) for e in self.experts],
        }

    @staticmethod
    def from_dict(d: dict, palette: list[str] | None = None) -> "Lineup":
        palette = palette or PALETTE
        host = d.get("host") or {}
        experts = []
        for i, e in enumerate(d.get("experts") or []):
            experts.append(Expert(
                id=str(e.get("id") or f"e{i + 1}"),
                name=str(e.get("name") or f"专家{i + 1}"),
                occupation=str(e.get("occupation") or "—"),
                title=str(e.get("title") or "—"),
                stance=str(e.get("stance") or ""),
                style=str(e.get("style") or ""),
                background=str(e.get("background") or e.get("stance") or ""),
                color=str(e.get("color") or palette[i % len(palette)]),
            ))
        return Lineup(host_name=str(host.get("name") or "知遥"),
                      host_title=str(host.get("title") or "主持人"),
                      experts=experts)


@dataclass
class Message:
    debate_id: str
    round: int
    speaker_id: str
    speaker_name: str
    role: str                 # host | guest
    content: str
    meta: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=_now)


@dataclass
class Debate:
    id: str
    topic: str
    expert_count: int
    lineup: Lineup
    status: str = "created"   # created | running | done | failed
    round: int = 0
    consensus: list[str] = field(default_factory=list)
    disagreements: list[dict] = field(default_factory=list)
    summary: str = ""
    created_at: str = field(default_factory=_now)


# ---------------------------------------------------------------- 种子数据
SEED_TOPICS: list[dict] = [
    {
        "id": "seed_ai_junior",
        "topic": "AI 编程工具会取代初级程序员吗？",
        "lineup": {
            "host": {"name": "知遥", "title": "主持人"},
            "experts": [
                {"id": "e1", "name": "林一舟", "occupation": "AI 开发者工具", "title": "AI 编程产品创始人",
                 "stance": "三年内初级岗位需求会明显萎缩，先拥抱工具的人形成代差优势",
                 "style": "语速快、爱用类比"},
                {"id": "e2", "name": "沈观澜", "occupation": "传统软件交付", "title": "主导过 3 次 AI 落地、两次烂尾的 CTO",
                 "stance": "代码生成只是环节之一，需求澄清与线上责任无法交给模型", "style": "爱用数据泼冷水"},
                {"id": "e3", "name": "江野", "occupation": "大模型应用工程", "title": "每天写 Prompt 与评测的工程师",
                 "stance": "不站队，先把评测和回滚做扎实，再谈替代", "style": "务实、爱举踩坑例子"},
                {"id": "e4", "name": "陈也", "occupation": "中小企业数字化", "title": "付费用过 6 款 AI 工具的中小企业主",
                 "stance": "只关心能不能少招人、少加班，别的都是虚的", "style": "大白话、讲真金白银"},
            ],
        },
    },
    {
        "id": "seed_sme_ai",
        "topic": "中小企业现在该不该全员上 AI 工作流？",
        "lineup": {
            "host": {"name": "知遥", "title": "主持人"},
            "experts": [
                {"id": "e1", "name": "苏未", "occupation": "组织与流程", "title": "参与过企业数字化改造的顾问",
                 "stance": "流程没梳理清楚就上 AI，只会把混乱自动化", "style": "追问责任与边界"},
                {"id": "e2", "name": "林一舟", "occupation": "AI 应用创业", "title": "AI SaaS 创业者",
                 "stance": "窗口期有限，先小范围全员试用再收敛", "style": "激进、看机会"},
                {"id": "e3", "name": "陈也", "occupation": "中小企业经营", "title": "50 人规模公司老板",
                 "stance": "员工培训成本比软件费用更高，这是真实约束", "style": "算账式表达"},
                {"id": "e4", "name": "沈观澜", "occupation": "企业 IT 治理", "title": "负责合规与数据安全的 CTO",
                 "stance": "客户数据外泄的风险必须先于效率被评估", "style": "谨慎、讲风险清单"},
            ],
        },
    },
    {
        "id": "seed_cost_effect",
        "topic": "大模型应用应该先做效果还是先控成本？",
        "lineup": {
            "host": {"name": "知遥", "title": "主持人"},
            "experts": [
                {"id": "e1", "name": "江野", "occupation": "推理工程", "title": "负责线上推理成本的工程师",
                 "stance": "先控成本，否则效果再好也上不了线", "style": "摆数字、讲单价"},
                {"id": "e2", "name": "林一舟", "occupation": "AI 产品", "title": "以体验口碑取胜的产品负责人",
                 "stance": "先做效果拿到用户，成本随规模优化", "style": "强调增长"},
                {"id": "e3", "name": "沈观澜", "occupation": "企业采购", "title": "按 ROI 审批预算的技术管理者",
                 "stance": "没有单位经济性，试点结束就是终点", "style": "算 ROI"},
                {"id": "e4", "name": "苏未", "occupation": "可持续与合规", "title": "关注算力与责任的行业研究员",
                 "stance": "成本不能只算钱，能耗与合规也是成本", "style": "温和但坚持"},
            ],
        },
    },
    {
        "id": "seed_edu_ai",
        "topic": "中小学该不该全面引入 AI 助教？",
        "lineup": {
            "host": {"name": "知遥", "title": "主持人"},
            "experts": [
                {"id": "e1", "name": "苏未", "occupation": "教育伦理", "title": "科技伦理研究员",
                 "stance": "未成年人的数据与发展权优先于效率", "style": "追问权责"},
                {"id": "e2", "name": "林一舟", "occupation": "教育科技", "title": "AI 学习产品创始人",
                 "stance": "师资缺口客观存在，AI 助教是规模化补位", "style": "乐观、讲普及"},
                {"id": "e3", "name": "陈也", "occupation": "家长视角", "title": "两个孩子的父亲",
                 "stance": "担心孩子只会问 AI，不会自己思考", "style": "说生活里的例子"},
                {"id": "e4", "name": "江野", "occupation": "教学工具研发", "title": "做过课堂试点的一线工程师",
                 "stance": "先做可控的作业辅导场景，别一上来全学科", "style": "讲试点细节"},
            ],
        },
    },
    {
        "id": "seed_remote_work",
        "topic": "远程办公三年后，我们该回到办公室吗？",
        "lineup": {
            "host": {"name": "知遥", "title": "主持人"},
            "experts": [
                {"id": "e1", "name": "陈也", "occupation": "团队管理", "title": "全员远程三年的公司负责人",
                 "stance": "远程能招到更好的人，协作靠制度不靠工位", "style": "讲自己公司"},
                {"id": "e2", "name": "沈观澜", "occupation": "研发效能", "title": "负责新人培养的技术总监",
                 "stance": "新人成长速度在远程环境明显下降", "style": "讲带人经历"},
                {"id": "e3", "name": "苏未", "occupation": "组织行为", "title": "研究团队凝聚力的学者",
                 "stance": "信任靠高频弱连接维持，办公室仍有价值", "style": "引研究结论"},
                {"id": "e4", "name": "江野", "occupation": "工程协作", "title": "跨时区协作的工程师",
                 "stance": "混合办公最现实，但必须重设会议规则", "style": "务实、讲机制"},
            ],
        },
    },
]

# 内置嘉宾池：阵容生成失败时的降级来源（保证任何情况下都能开场）
FALLBACK_POOL: list[dict] = [
    {"name": "林一舟", "occupation": "AI 应用", "title": "AI 产品创业者",
     "stance": "技术红利窗口有限，先上船的人吃红利", "style": "语速快、爱用类比"},
    {"name": "沈观澜", "occupation": "企业 IT", "title": "主导过多次 AI 落地的 CTO",
     "stance": "落地卡在数据、成本和组织协同上", "style": "爱用数据泼冷水"},
    {"name": "江野", "occupation": "大模型工程", "title": "一线大模型应用工程师",
     "stance": "不站队，只谈具体怎么做到", "style": "务实、爱举踩坑例子"},
    {"name": "苏未", "occupation": "科技伦理", "title": "科技伦理研究员",
     "stance": "责任归属与用户知情权决定这条路能走多远", "style": "温和但坚持"},
    {"name": "陈也", "occupation": "普通用户", "title": "付费用过多种 AI 工具的中小企业主",
     "stance": "别谈趋势，只关心能否省下真金白银的时间", "style": "大白话"},
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
                CREATE TABLE IF NOT EXISTS topics (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    lineup TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS debates (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    expert_count INTEGER NOT NULL,
                    lineup TEXT NOT NULL,
                    status TEXT NOT NULL,
                    round INTEGER DEFAULT 0,
                    consensus TEXT DEFAULT '[]',
                    disagreements TEXT DEFAULT '[]',
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
            for t in SEED_TOPICS:
                conn.execute(
                    "INSERT OR REPLACE INTO topics (id, topic, lineup, created_at) VALUES (?,?,?,?)",
                    (t["id"], t["topic"], json.dumps(t["lineup"], ensure_ascii=False), _now()),
                )

    # ---------------- topics（样例数据） ----------------
    def list_topics(self) -> list[dict]:
        with self._txn() as conn:
            rows = conn.execute("SELECT * FROM topics").fetchall()
        return [{"id": r["id"], "topic": r["topic"],
                 "lineup": Lineup.from_dict(json.loads(r["lineup"])).to_dict()} for r in rows]

    # ---------------- debates ----------------
    def create_debate(self, topic: str, lineup: Lineup) -> Debate:
        d = Debate(id=uuid.uuid4().hex[:12], topic=topic,
                   expert_count=len(lineup.experts), lineup=lineup)
        with self._txn() as conn:
            conn.execute(
                "INSERT INTO debates (id, topic, expert_count, lineup, status, round, consensus,"
                " disagreements, summary, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (d.id, d.topic, d.expert_count, json.dumps(lineup.to_dict(), ensure_ascii=False),
                 d.status, 0, "[]", "[]", "", d.created_at),
            )
        return d

    def get_debate(self, debate_id: str) -> Debate | None:
        with self._txn() as conn:
            r = conn.execute("SELECT * FROM debates WHERE id=?", (debate_id,)).fetchone()
        return self._row_to_debate(r) if r else None

    def list_debates(self, limit: int = 50) -> list[Debate]:
        with self._txn() as conn:
            rows = conn.execute(
                "SELECT * FROM debates ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_debate(r) for r in rows]

    @staticmethod
    def _row_to_debate(r: sqlite3.Row) -> Debate:
        return Debate(
            id=r["id"], topic=r["topic"], expert_count=r["expert_count"],
            lineup=Lineup.from_dict(json.loads(r["lineup"])), status=r["status"], round=r["round"],
            consensus=json.loads(r["consensus"] or "[]"),
            disagreements=json.loads(r["disagreements"] or "[]"),
            summary=r["summary"], created_at=r["created_at"],
        )

    def update_debate(self, debate_id: str, status: str | None = None, round: int | None = None,
                      summary: str | None = None, consensus: list[str] | None = None,
                      disagreements: list[dict] | None = None) -> None:
        fields, values = [], []
        if status is not None:
            fields.append("status=?"); values.append(status)
        if round is not None:
            fields.append("round=?"); values.append(round)
        if summary is not None:
            fields.append("summary=?"); values.append(summary)
        if consensus is not None:
            fields.append("consensus=?"); values.append(json.dumps(consensus, ensure_ascii=False))
        if disagreements is not None:
            fields.append("disagreements=?"); values.append(json.dumps(disagreements, ensure_ascii=False))
        if not fields:
            return
        values.append(debate_id)
        with self._txn() as conn:
            conn.execute(f"UPDATE debates SET {','.join(fields)} WHERE id=?", values)

    # ---------------- messages ----------------
    def add_message(self, m: Message) -> Message:
        with self._txn() as conn:
            conn.execute(
                "INSERT INTO messages (id, debate_id, round, speaker_id, speaker_name, role, content,"
                " meta, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (m.id, m.debate_id, m.round, m.speaker_id, m.speaker_name, m.role,
                 m.content, json.dumps(m.meta, ensure_ascii=False), m.created_at),
            )
        return m

    def list_messages(self, debate_id: str) -> list[Message]:
        with self._txn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE debate_id=? ORDER BY rowid", (debate_id,)).fetchall()
        return [
            Message(id=r["id"], debate_id=r["debate_id"], round=r["round"], speaker_id=r["speaker_id"],
                    speaker_name=r["speaker_name"], role=r["role"], content=r["content"],
                    meta=json.loads(r["meta"] or "{}"), created_at=r["created_at"])
            for r in rows
        ]
