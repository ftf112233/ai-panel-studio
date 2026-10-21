"""FastAPI 入口：REST 建单/查单 + SSE 实时推流 + 静态托管前端。"""
from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents.guest import chunk_text
from .config import settings
from .llm.client import build_client
from .orchestrator import Orchestrator
from .storage.db import Repository

app = FastAPI(title="AI 圆桌讨论", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

repo = Repository(settings.db_path)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")


class CreateDebateReq(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    persona_ids: list[str] = Field(min_length=3, max_length=5)  # 要求：3-5 位 AI 嘉宾


# ---------------------------------------------------------------- REST API
@app.get("/api/personas")
def api_personas():
    return [
        {
            "id": p.id, "name": p.name, "title": p.title, "background": p.background,
            "stance": p.stance, "style": p.style, "avatar": p.avatar, "color": p.color,
        }
        for p in repo.list_personas()
    ]


@app.post("/api/debates")
def api_create_debate(req: CreateDebateReq):
    personas = repo.get_personas(req.persona_ids)
    if len(personas) < 3:
        raise HTTPException(400, "至少需要 3 位有效嘉宾（要求 3-5 位）")
    d = repo.create_debate(req.topic.strip(), [p.id for p in personas])
    return {"id": d.id, "topic": d.topic, "status": d.status, "persona_ids": d.persona_ids}


@app.get("/api/debates")
def api_list_debates():
    out = []
    for d in repo.list_debates():
        msgs = repo.list_messages(d.id)
        out.append({
            "id": d.id, "topic": d.topic, "status": d.status, "round": d.round,
            "created_at": d.created_at, "summary": d.summary,
            "persona_ids": d.persona_ids, "message_count": len(msgs),
        })
    return out


@app.get("/api/debates/{debate_id}")
def api_get_debate(debate_id: str):
    d = repo.get_debate(debate_id)
    if not d:
        raise HTTPException(404, "圆桌不存在")
    return {
        "id": d.id, "topic": d.topic, "status": d.status, "round": d.round,
        "summary": d.summary, "persona_ids": d.persona_ids,
        "messages": [
            {"id": m.id, "round": m.round, "speaker_id": m.speaker_id, "speaker_name": m.speaker_name,
             "role": m.role, "content": m.content, "meta": m.meta, "created_at": m.created_at}
            for m in repo.list_messages(d.id)
        ],
    }


@app.get("/api/health")
def api_health():
    return {"ok": True, "mode": "mock" if (settings.mock or not settings.deepseek_api_key) else "deepseek",
            "model": settings.model}


# ---------------------------------------------------------------- SSE 推流
def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _event_stream(debate_id: str) -> AsyncIterator[str]:
    d = repo.get_debate(debate_id)
    if not d:
        yield _sse({"event": "error", "data": {"message": "圆桌不存在", "recoverable": False}})
        return

    personas = repo.get_personas(d.persona_ids)
    if len(personas) < 2:
        yield _sse({"event": "error", "data": {"message": "嘉宾配置无效", "recoverable": False}})
        return

    # 已结束的圆桌：回放存档（支持刷新页面 / 归档页直接观看）
    if d.status in {"done", "failed"}:
        yield _sse({
            "event": "participants",
            "data": {
                "debate_id": d.id, "topic": d.topic,
                "host": {"id": "host", "name": "知遥", "avatar": "知", "color": "#495057"},
                "guests": [{"id": p.id, "name": p.name, "title": p.title, "avatar": p.avatar, "color": p.color}
                           for p in personas],
            },
        })
        # 回放也逐字流出，避免"一次性刷出整场讨论"
        for m in repo.list_messages(d.id):
            yield _sse({"event": "thinking", "data": {"speaker": m.speaker_id, "name": m.speaker_name}})
            await asyncio.sleep(0.4)
            yield _sse({"event": "speaker_start",
                        "data": {"speaker": m.speaker_id, "name": m.speaker_name}})
            for seg in chunk_text(m.content, size=3):
                await asyncio.sleep(0.02)
                yield _sse({"event": "delta", "data": {"speaker": m.speaker_id, "text": seg}})
            yield _sse({"event": "speaker_end", "data": {"speaker": m.speaker_id}})
        yield _sse({"event": "done", "data": {"debate_id": d.id, "summary": d.summary, "replay": True}})
        return

    orch = Orchestrator(d, personas, repo, llm=build_client(settings), settings=settings)
    try:
        async for ev in orch.run():
            yield _sse(ev)
    except Exception as e:  # 生成器层面的最后兜底
        yield _sse({"event": "error", "data": {"message": str(e), "recoverable": True}})


@app.get("/api/debates/{debate_id}/stream")
def api_stream(debate_id: str):
    return StreamingResponse(
        _event_stream(debate_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.exception_handler(Exception)
async def unhandled(request, exc):  # pragma: no cover
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
