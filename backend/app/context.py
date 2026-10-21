"""上下文裁剪：控制 token，同时保证嘉宾能接得上话。

策略：最近 N 条原样保留；更早的压缩成一句摘要。
作业点评关注「上下文工程」，这里是最小的可解释实现。
"""
from __future__ import annotations

from .storage.db import Message


def recent_digest(messages: list[Message], window: int = 4) -> str:
    tail = messages[-window:]
    return "\n".join(f"[{m.speaker_name}] {_clip(m.content, 160)}" for m in tail)


def visible_history(messages: list[Message], window: int = 4, max_chars: int = 6000) -> str:
    """给嘉宾看的上下文：最近 window 条完整 + 更早内容的一句话压缩。"""
    if not messages:
        return "（暂无）"
    parts: list[str] = []

    older = messages[:-window]
    if older:
        parts.append("更早讨论摘要：")
        for m in older[-6:]:
            parts.append(f"- {m.speaker_name}：{_clip(m.content, 80)}")
        parts.append("")

    parts.append("最近发言：")
    for m in messages[-window:]:
        parts.append(f"- {m.speaker_name}：{m.content}")

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = "...(已截断)\n" + text[-max_chars:]
    return text


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"
