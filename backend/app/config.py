"""全局配置。

设计要点：
1. 没有配置 DEEPSEEK_API_KEY 时自动进入 MOCK 模式，保证任何环境都能跑通演示；
2. 所有可调参数集中在此，便于实验（如调度策略对比实验只需改 MAX_SPEECHES_PER_ROUND）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _load_dotenv() -> None:
    """极简 .env 加载，避免强依赖 python-dotenv（沙箱/离线环境可用）。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _as_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(v: str | None, default: int) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # ---- LLM ----
    deepseek_api_key: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(
        default_factory=lambda: os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    model: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))
    # 无 Key / 显式开关 -> Mock 流式，保证可演示
    mock: bool = field(
        default_factory=lambda: _as_bool(os.environ.get("MOCK"), None)
        if os.environ.get("MOCK") is not None
        else not os.environ.get("DEEPSEEK_API_KEY", "")
    )
    request_timeout: int = field(default_factory=lambda: _as_int(os.environ.get("LLM_TIMEOUT"), 60))
    max_retry: int = 1  # 失败重试次数（作业要求：兜底策略）

    # ---- 编排参数（实验可调）----
    max_rounds: int = field(default_factory=lambda: _as_int(os.environ.get("MAX_ROUNDS"), 4))
    max_speeches_per_round: int = field(
        default_factory=lambda: _as_int(os.environ.get("MAX_SPEECHES_PER_ROUND"), 4)
    )
    history_window: int = 4          # 嘉宾可见的最近发言条数
    max_history_chars: int = 6000    # 超出后对更早发言做摘要压缩

    # ---- 存储 ----
    db_path: str = field(
        default_factory=lambda: os.environ.get(
            "DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "roundtable.db")
        )
    )


settings = Settings()
