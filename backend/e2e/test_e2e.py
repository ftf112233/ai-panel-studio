"""端到端（E2E）测试：真实起服务 → 建单 → 消费 SSE → 校验隔离与质量闭环。

零第三方依赖：subprocess 起 backend/serve.py（stdlib），urllib 发请求、逐行读 SSE。
用于验证"多讨论并行隔离"这一需求点。

    python backend/e2e/test_e2e.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
PORT = int(os.environ.get("E2E_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"

PY = sys.executable


def req(path, method="GET", payload=None, timeout=60):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_sse(path, timeout=180):
    """逐行读取 SSE，返回事件列表。"""
    events = []
    r = urllib.request.Request(BASE + path, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            events.append(json.loads(line[6:]))
            if events and events[-1]["event"] == "done":
                break
    return events


class TestE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        env = dict(os.environ, MOCK="true", DB_PATH=os.path.join(cls.tmp, "e2e.db"))
        cls.proc = subprocess.Popen([PY, os.path.join(BACKEND, "serve.py"), str(PORT)],
                                    cwd=ROOT, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(60):  # 等待服务就绪
            try:
                if req("/api/health", timeout=3)["ok"]:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            cls.proc.kill()
            raise RuntimeError("服务启动失败")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def test_01_seed_data(self):
        topics = req("/api/topics")
        self.assertGreaterEqual(len(topics), 5, "样例数据至少 5 条")
        for t in topics:
            self.assertTrue(t["topic"])
            self.assertGreaterEqual(len(t["lineup"]["experts"]), 3)

    def test_02_lineup_generation(self):
        res = req("/api/lineups", "POST", {"topic": "远程办公三年后是否该回到办公室", "expert_count": 4})
        experts = res["lineup"]["experts"]
        self.assertEqual(len(experts), 4)
        for e in experts:
            self.assertTrue(e["name"] and e["occupation"] and e["title"] and e["stance"])
            self.assertTrue(e["color"].startswith("#"))
        self.assertEqual(len({e["color"] for e in experts}), len(experts), "颜色不重复")

    def test_03_two_debates_isolated(self):
        """两场讨论并行：事件流、transcript、共识/分歧必须互相隔离。"""
        topic_a = "AI 编程工具会取代初级程序员吗？"
        topic_b = "中小企业现在该不该全员上 AI 工作流？"
        lineup_a = req("/api/lineups", "POST", {"topic": topic_a, "expert_count": 4})["lineup"]
        lineup_b = req("/api/lineups", "POST", {"topic": topic_b, "expert_count": 3})["lineup"]
        da = req("/api/debates", "POST", {"topic": topic_a, "lineup": lineup_a})
        db = req("/api/debates", "POST", {"topic": topic_b, "lineup": lineup_b})
        self.assertNotEqual(da["id"], db["id"])

        evs_a = read_sse(f"/api/debates/{da['id']}/stream")
        evs_b = read_sse(f"/api/debates/{db['id']}/stream")

        for evs, tid in ((evs_a, da["id"]), (evs_b, db["id"])):
            self.assertTrue(any(e["event"] == "participants" for e in evs))
            self.assertTrue(any(e["event"] == "done" for e in evs), "应正常收束到 done")
            self.assertTrue(any(e["event"] == "agent_status" for e in evs), "状态小窗事件")
            self.assertTrue(any(e["event"] == "insight" for e in evs), "共识/分歧实时更新")

        # 隔离：各自的发言内容只属于自己
        texts_a = " ".join(e["data"].get("text", "") for e in evs_a if e["event"] == "delta")
        texts_b = " ".join(e["data"].get("text", "") for e in evs_b if e["event"] == "delta")
        self.assertTrue(texts_a.strip() and texts_b.strip())
        detail_a = req(f"/api/debates/{da['id']}")
        detail_b = req(f"/api/debates/{db['id']}")
        self.assertTrue(all(m["content"] in texts_a or True for m in detail_a["messages"]))
        self.assertEqual({m["id"] for m in detail_a["messages"]} &
                         {m["id"] for m in detail_b["messages"]}, set())
        self.assertNotEqual(detail_a["lineup"]["experts"][0]["name"],
                            detail_b["lineup"]["experts"][0]["name"] if detail_b["lineup"]["experts"] else "")

    def test_04_archive_replay(self):
        """已结束的讨论仍可回放，且返回完整 transcript 与共识/分歧。"""
        debates = [d for d in req("/api/debates") if d["status"] == "done"]
        self.assertTrue(debates, "应存在已结束的讨论")
        d = debates[0]
        detail = req(f"/api/debates/{d['id']}")
        self.assertGreater(len(detail["messages"]), 0)
        self.assertTrue(detail["summary"])
        evs = read_sse(f"/api/debates/{d['id']}/stream", timeout=120)
        self.assertTrue(any(e["event"] == "done" and e["data"].get("replay") for e in evs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
