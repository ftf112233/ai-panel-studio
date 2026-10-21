"""FastAPI 入口：REST（样例话题 / 阵容生成 / 建单 / 查单）+ SSE 实时推流 + 静态托管前端。

API 契约详见 docs/API文档.md。Key 只从后端环境变量读取，绝不下发到浏览器。
"""
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
from .agents.lineup import LineupAgent
from .config import settings
from .llm.client import build_client
from .orchestrator import Orchestrator
from .storage.db import Lineup, Repository

app = FastAPI(title="AI Panel Studio", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

repo = Repository(settings.db_path)
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")


class LineupReq(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    expert_count: int = Field(default=4, ge=2, le=5)


class CreateDebateReq(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    lineup: dict


# ---------------------------------------------------------------- 样例数据
@app.get("/api/topics")
def api_topics():
    """≥5 条高质量样例数据：预设话题 + 对应嘉宾阵容。"""
    return repo.list_topics()


# ---------------------------------------------------------------- 阵容生成
@app.post("/api/lineups")
async def api_lineups(req: LineupReq):
    agent = LineupAgent(build_client(settings))
    lineup = await agent.generate(req.topic.strip(), req.expert_count)
    return {"topic": req.topic.strip(), "lineup": lineup.to_dict()}


# ---------------------------------------------------------------- 圆桌
@app.post("/api/debates")
def api_create_debate(req: CreateDebateReq):
    lineup = Lineup.from_dict(req.lineup)
    if len(lineup.experts) < 2:
        raise HTTPException(400, "阵容至少需要 2 位专家")
    d = repo.create_debate(req.topic.strip(), lineup)
    return {"id": d.id, "topic": d.topic, "status": d.status,
            "expert_count": d.expert_count, "lineup": d.lineup.to_dict()}


@app.get("/api/debates")
def api_list_debates():
    out = []
    for d in repo.list_debates():
        out.append({
            "id": d.id, "topic": d.topic, "status": d.status, "round": d.round,
            "created_at": d.created_at, "summary": d.summary,
            "expert_count": d.expert_count,
            "experts": [{"name": e.name, "title": e.title, "color": e.color} for e in d.lineup.experts],
            "message_count": len(repo.list_messages(d.id)),
        })
    return out


@app.get("/api/debates/{debate_id}")
def api_get_debate(debate_id: str):
    d = repo.get_debate(debate_id)
    if not d:
        raise HTTPException(404, "圆桌不存在")
    return _debate_payload(d)


def _debate_payload(d) -> dict:
    return {
        "id": d.id, "topic": d.topic, "status": d.status, "round": d.round,
        "summary": d.summary, "consensus": d.consensus, "disagreements": d.disagreements,
        "lineup": d.lineup.to_dict(),
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
    if len(d.lineup.experts) < 2:
        yield _sse({"event": "error", "data": {"message": "阵容无效", "recoverable": False}})
        return

    # 已结束/异常：逐字回放存档（刷新页面或归档观看，仍保持流式观感）
    if d.status in {"done", "failed"}:
        yield _sse({"event": "participants", "data": {
            "debate_id": d.id, "topic": d.topic,
            "host": {"id": "host", "name": d.lineup.host_name, "title": d.lineup.host_title,
                     "avatar": d.lineup.host_name[:1], "color": "#495057"},
            "guests": [{"id": e.id, "name": e.name, "occupation": e.occupation, "title": e.title,
                        "stance": e.stance, "avatar": e.avatar, "color": e.color}
                       for e in d.lineup.experts]}})
        yield _sse({"event": "insight", "data": {"consensus": d.consensus,
                                                 "disagreements": d.disagreements}})
        for m in repo.list_messages(d.id):
            yield _sse({"event": "thinking",
                        "data": {"speaker": m.speaker_id, "name": m.speaker_name}})
            await asyncio.sleep(0.4)
            yield _sse({"event": "speaker_start",
                        "data": {"speaker": m.speaker_id, "name": m.speaker_name,
                                 "occupation": "", "title": "", "color": "#868e96"}})
            for seg in chunk_text(m.content, size=3):
                await asyncio.sleep(0.02)
                yield _sse({"event": "delta", "data": {"speaker": m.speaker_id, "text": seg}})
            yield _sse({"event": "speaker_end", "data": {"speaker": m.speaker_id}})
        yield _sse({"event": "done", "data": {"debate_id": d.id, "summary": d.summary, "replay": True}})
        return

    orch = Orchestrator(d, repo, llm=build_client(settings), settings=settings)
    try:
        async for ev in orch.run():
            yield _sse(ev)
    except Exception as e:
        yield _sse({"event": "error", "data": {"message": str(e), "recoverable": True}})


@app.get("/api/debates/{debate_id}/stream")
def api_stream(debate_id: str):
    return StreamingResponse(
        _event_stream(debate_id), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.exception_handler(Exception)
async def unhandled(request, exc):  # pragma: no cover
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
