"""阵容生成 Agent：按话题 + 专家人数动态生成主持人 + 专家阵容。

降级链：LLM 生成 → JSON 解析失败重试 1 次 → 内置嘉宾池补全/替换。
保证任何情况下都能凑出「专家人数」个立场不同的专家（作业要求：用户确认后进入演播厅）。
"""
from __future__ import annotations

import hashlib

from ..llm.client import BaseLLMClient
from ..storage.db import FALLBACK_POOL, PALETTE, Expert, Lineup
from .base import BaseAgent, load_prompt

LINEUP_PROMPT = "lineup.v1.json"


class LineupAgent(BaseAgent):
    def __init__(self, llm: BaseLLMClient):
        super().__init__(llm, name="选角导演", speaker_id="lineup")
        self.prompt = load_prompt(LINEUP_PROMPT)

    async def generate(self, topic: str, expert_count: int) -> Lineup:
        expert_count = max(2, min(5, expert_count))
        messages = [
            {"role": "system", "content": self.prompt["system"]},
            {"role": "user", "content": self._fmt(
                self.prompt["user"], topic=topic, expert_count=expert_count)},
        ]
        obj = await self._call_json(messages, retries=1, temperature=1.0)
        return self._normalize(obj, topic, expert_count)

    # ------------------------------------------------------------------
    def _normalize(self, obj: dict | None, topic: str, expert_count: int) -> Lineup:
        raw = (obj or {}).get("experts") or []
        host = (obj or {}).get("host") or {}
        lineup = Lineup(host_name=str(host.get("name") or "知遥"),
                        host_title=str(host.get("title") or "主持人"))

        picked: list[dict] = []
        for e in raw:
            if not isinstance(e, dict) or not e.get("name"):
                continue
            picked.append(e)
        if len(picked) < expert_count:  # 不足则从内置池补足
            picked += self._from_pool(expert_count - len(picked), offset=len(picked))
        picked = picked[:expert_count]

        seen: set[str] = set()
        for i, e in enumerate(picked):
            name = str(e.get("name") or f"专家{i + 1}")
            if name in seen:  # 重名去重
                name = f"{name}·{i + 1}"
            seen.add(name)
            lineup.experts.append(Expert(
                id=f"e{i + 1}",
                name=name,
                occupation=str(e.get("occupation") or "—"),
                title=str(e.get("title") or "—"),
                stance=str(e.get("stance") or f"围绕「{topic}」有自己的独立判断"),
                style=str(e.get("style") or ""),
                background=str(e.get("background") or e.get("stance") or ""),
                color=PALETTE[i % len(PALETTE)],   # 颜色由代码分配，保证不重复
            ))
        return lineup

    @staticmethod
    def _from_pool(n: int, offset: int = 0) -> list[dict]:
        out = []
        for i in range(n):
            out.append(dict(FALLBACK_POOL[(offset + i) % len(FALLBACK_POOL)]))
        return out


def mock_lineup(topic: str, expert_count: int) -> dict:
    """Mock 客户端用的确定性阵容（同一话题每次一致，便于演示与测试）。"""
    h = int(hashlib.md5(topic.encode("utf-8")).hexdigest(), 16)
    names = ["林一舟", "沈观澜", "江野", "苏未", "陈也"]
    roles = ["技术乐观", "落地怀疑", "一线工程", "风险伦理", "用户视角"]
    experts = []
    for i in range(expert_count):
        idx = (h + i) % len(names)
        experts.append({
            "name": names[idx],
            "occupation": ["AI 应用", "企业 IT", "大模型工程", "科技伦理", "终端用户"][idx],
            "title": f"{roles[idx]}派 · 关注「{topic[:8]}」",
            "stance": FALLBACK_POOL[idx]["stance"],
            "style": FALLBACK_POOL[idx]["style"],
        })
    return {"host": {"name": "知遥", "title": "主持人"}, "experts": experts}
