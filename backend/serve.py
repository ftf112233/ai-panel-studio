"""零依赖备用服务（标准库 http.server），用于未安装 fastapi 时的本地演示。

功能与 backend/app/main.py 的路由一致：REST + SSE + 静态托管。
仅用于本地演示/离线验证，生产仍用 uvicorn + FastAPI。

    python backend/serve.py            # 默认 8000 端口（未配 Key 时自动 Mock 流式）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings  # noqa: E402
from app.llm.client import build_client  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.storage.db import Repository  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
repo = Repository(settings.db_path)

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".ico": "image/x-icon"}


def _json_response(h, code: int, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


async def _events(debate_id: str):
    d = repo.get_debate(debate_id)
    if not d:
        yield {"event": "error", "data": {"message": "圆桌不存在", "recoverable": False}}
        return
    personas = repo.get_personas(d.persona_ids)
    if len(personas) < 2:
        yield {"event": "error", "data": {"message": "嘉宾配置无效", "recoverable": False}}
        return
    if d.status in {"done", "failed"}:
        yield {"event": "participants", "data": {
            "debate_id": d.id, "topic": d.topic,
            "host": {"id": "host", "name": "知遥", "avatar": "知", "color": "#495057"},
            "guests": [{"id": p.id, "name": p.name, "title": p.title, "avatar": p.avatar, "color": p.color}
                       for p in personas]}}
        # 回放也逐字流出，避免"一次性刷出整场讨论"
        for m in repo.list_messages(d.id):
            yield {"event": "thinking", "data": {"speaker": m.speaker_id, "name": m.speaker_name}}
            await asyncio.sleep(0.4)
            yield {"event": "speaker_start", "data": {"speaker": m.speaker_id, "name": m.speaker_name}}
            for i in range(0, len(m.content), 3):
                await asyncio.sleep(0.02)
                yield {"event": "delta", "data": {"speaker": m.speaker_id, "text": m.content[i:i + 3]}}
            yield {"event": "speaker_end", "data": {"speaker": m.speaker_id}}
        yield {"event": "done", "data": {"debate_id": d.id, "summary": d.summary, "replay": True}}
        return
    orch = Orchestrator(d, personas, repo, llm=build_client(settings), settings=settings)
    async for ev in orch.run():
        yield ev


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静音默认日志，避免刷屏
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self._api(path)
        return self._static(path)

    def _static(self, path: str):
        if path in ("/", ""):
            path = "/index.html"
        full = os.path.normpath(os.path.join(FRONTEND, path.lstrip("/")))
        if not full.startswith(FRONTEND) or not os.path.isfile(full):
            self.send_error(404)
            return
        body = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api(self, path: str):
        if path == "/api/health":
            return _json_response(self, 200, {
                "ok": True,
                "mode": "mock" if (settings.mock or not settings.deepseek_api_key) else "deepseek",
                "model": settings.model})
        if path == "/api/personas":
            return _json_response(self, 200, [
                {"id": p.id, "name": p.name, "title": p.title, "background": p.background,
                 "stance": p.stance, "style": p.style, "avatar": p.avatar, "color": p.color}
                for p in repo.list_personas()])
        if path == "/api/debates":
            return _json_response(self, 200, [
                {"id": d.id, "topic": d.topic, "status": d.status, "round": d.round,
                 "created_at": d.created_at, "summary": d.summary,
                 "persona_ids": d.persona_ids, "message_count": len(repo.list_messages(d.id))}
                for d in repo.list_debates()])

        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "debates":
            debate_id = parts[2]
            d = repo.get_debate(debate_id)
            if not d:
                return _json_response(self, 404, {"detail": "圆桌不存在"})
            return _json_response(self, 200, {
                "id": d.id, "topic": d.topic, "status": d.status, "round": d.round,
                "summary": d.summary, "persona_ids": d.persona_ids,
                "messages": [{"id": m.id, "round": m.round, "speaker_id": m.speaker_id,
                              "speaker_name": m.speaker_name, "role": m.role, "content": m.content,
                              "meta": m.meta, "created_at": m.created_at}
                             for m in repo.list_messages(d.id)]})

        if len(parts) == 4 and parts[3] == "stream":
            return self._sse(parts[2])
        return _json_response(self, 404, {"detail": "not found"})

    def _sse(self, debate_id: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        lock = threading.Lock()
        loop = asyncio.new_event_loop()
        agen = _events(debate_id)
        try:
            while True:
                try:
                    ev = loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break
                with lock:
                    self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            loop.close()
            # SSE 结束即关闭连接，避免客户端一直挂着等（之前会挂到超时）
            self.close_connection = True

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/debates":
            return _json_response(self, 404, {"detail": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return _json_response(self, 400, {"detail": "非法 JSON"})
        topic = str(payload.get("topic", "")).strip()
        ids = payload.get("persona_ids") or []
        if len(topic) < 2 or len(ids) < 3:
            return _json_response(self, 400, {"detail": "主题至少 2 字，嘉宾 3-5 位"})
        personas = repo.get_personas(ids)
        d = repo.create_debate(topic, [p.id for p in personas])
        return _json_response(self, 200, {"id": d.id, "topic": d.topic,
                                          "status": d.status, "persona_ids": d.persona_ids})


def main(port: int = 8000):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    mode = "MOCK 流式" if (settings.mock or not settings.deepseek_api_key) else f"DeepSeek({settings.model})"
    print(f"AI 圆桌讨论 已启动： http://127.0.0.1:{port}   模式：{mode}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
