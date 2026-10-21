"""Agent 基类：Prompt 版本加载 + 结构化输出校验 + 重试 + 降级。

作业红线要求「禁止一次性魔法 Prompt」，因此所有 Prompt 都放在 backend/prompts/*.json，
带 version 与 changelog，随代码一起进 Git，迭代过程可追溯。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts")

_cache: dict[str, dict] = {}


def load_prompt(filename: str) -> dict:
    if filename not in _cache:
        with open(os.path.join(PROMPTS_DIR, filename), "r", encoding="utf-8") as f:
            _cache[filename] = json.load(f)
    return _cache[filename]


def extract_json(text: str) -> dict | None:
    """从模型输出中稳健地取出 JSON。

    模型偶尔会在 JSON 外面包 ```json 或前后加解释，这里做宽容解析；
    解析不出来返回 None，由上层决定重试或降级（作业要求：兜底策略）。
    """
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(cleaned[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


class BaseAgent:
    def __init__(self, llm, name: str, speaker_id: str):
        self.llm = llm
        self.name = name
        self.speaker_id = speaker_id

    async def _call_json(self, messages: list[dict], retries: int = 1, temperature: float = 0.7) -> dict | None:
        """调用一次 JSON 输出；失败重试 retries 次；全失败返回 None 交给上层降级。"""
        for _ in range(retries + 1):
            try:
                res = await self.llm.json_chat(messages, temperature=temperature)
                obj = extract_json(res.get("text", ""))
                if obj is not None:
                    return obj
            except Exception:
                continue
        return None

    @staticmethod
    def _fmt(template: str, **kwargs: Any) -> str:
        """安全格式化：允许模板里出现 JSON 花括号（已转义为 {{ }}）。"""
        out = template.replace("{{", "\x00").replace("}}", "\x01")
        out = out.format(**kwargs)
        return out.replace("\x00", "{").replace("\x01", "}")
