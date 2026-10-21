"""DeepSeek 流式客户端（OpenAI 兼容协议）+ Mock 流式客户端。

为什么自己写而不直接用 SDK：
1. 只需要 /chat/completions 的流式解析，自己写能精确控制 chunk 与异常；
2. httpx 延迟导入，Orchestrator 的单测在零依赖环境下也能跑。
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from typing import AsyncIterator

from ..config import Settings


class LLMError(Exception):
    """LLM 调用失败（超时/网络/限流）。"""


class BaseLLMClient:
    async def stream_chat(self, messages: list[dict], temperature: float = 0.9) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def json_chat(self, messages: list[dict], temperature: float = 0.7) -> dict:
        raise NotImplementedError


class DeepSeekClient(BaseLLMClient):
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def _url(self) -> str:
        return f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"

    async def stream_chat(self, messages: list[dict], temperature: float = 0.9) -> AsyncIterator[str]:
        import httpx  # 延迟导入

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as cli:
                async with cli.stream("POST", self._url, json=payload, headers=headers) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise LLMError(f"HTTP {resp.status_code}: {body[:200].decode('utf-8', 'ignore')}")
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content")
                        if delta:
                            yield delta
        except LLMError:
            raise
        except Exception as e:  # 网络/超时等统一包装，交给上层兜底
            raise LLMError(str(e)) from e

    async def json_chat(self, messages: list[dict], temperature: float = 0.7) -> dict:
        import httpx

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as cli:
                resp = await cli.post(self._url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                return {"text": data["choices"][0]["message"]["content"]}
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(str(e)) from e


class MockLLMClient(BaseLLMClient):
    """无 API Key 时的降级客户端：按句式切块 sleep 输出，前端体验与真实流式一致。"""

    def __init__(self, settings: Settings | None = None, chunk_delay: float = 0.045,
                 think_delay: float = 0.9):
        self.settings = settings
        # Mock 的节奏参数：chunk_delay 控制打字速度，think_delay 控制"思考中"停留时长
        self.chunk_delay = chunk_delay
        self.think_delay = think_delay

    async def stream_chat(self, messages: list[dict], temperature: float = 0.9) -> AsyncIterator[str]:
        # 先"思考"再出字：让前端的思考动画有真实停留，观感贴近真实 LLM 首字延迟
        await asyncio.sleep(self.think_delay)
        text = self._compose(messages)
        for seg in self._split(text):
            await asyncio.sleep(self.chunk_delay)
            yield seg

    async def json_chat(self, messages: list[dict], temperature: float = 0.7) -> dict:
        await asyncio.sleep(self.think_delay)
        return {"text": self._compose(messages)}

    @staticmethod
    def _split(text: str) -> list[str]:
        out, buf = [], ""
        for ch in text:
            buf += ch
            if len(buf) >= 3 or ch in "，。！？、；：":
                out.append(buf)
                buf = ""
        if buf:
            out.append(buf)
        return out

    @staticmethod
    def _compose(messages: list[dict]) -> str:
        # 延迟导入避免循环依赖（agents 会 import client）
        from ..agents.guest import mock_speech
        from ..agents.lineup import mock_lineup

        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        topic = last_user.split("「")[-1].split("」")[0] if "「" in last_user else "这个话题"

        # 阵容生成
        if "选角导演" in system:
            count = 4
            for token in last_user.replace("：", " ").split():
                if token.isdigit():
                    count = max(2, min(5, int(token)))
                    break
            return json.dumps(mock_lineup(topic, count), ensure_ascii=False)

        # 发言调度
        if "发言调度器" in system:
            ids = re.findall(r"- (e\d+)｜", last_user)
            last = last_user.split("上一位发言者：")[1].split("\n")[0].strip() if "上一位发言者：" in last_user else ""
            choices = [i for i in ids if i and i != last] or ids or ["e1"]
            return json.dumps({
                "speaker": random.choice(choices),
                "action": random.choice(["raise_hand", "supplement", "rebut"]),
                "thought": random.choice([
                    "刚才那句把我这点戳中了，我想接一句",
                    "这个焦点我还没说过，应该补上我的视角",
                    "他的结论下得太快，我要提个反例",
                ]),
            }, ensure_ascii=False)

        # 共识 / 分歧提炼
        if "议题分析员" in system:
            latest = last_user.split("最新发言：")[-1].strip()[:80] or "当前发言"
            return json.dumps({
                "consensus": [f"都认为「{topic}」不能只看技术本身"[:40]],
                "disagreements": [{"a": "乐观派", "b": "谨慎派",
                                   "point": f"{latest[:20]}…上节奏与代价谁先算"}],
            }, ensure_ascii=False)

        if "主持人" in system:
            # 主持人：返回决策 JSON（末条用户指令决定输出哪种 type）
            if '"type": "summary"' in last_user or "总结" in last_user:
                return json.dumps({
                    "type": "summary",
                    "content": f"这一轮下来，{topic} 的分歧其实很清楚：一边看机会窗口，一边看落地代价。"
                               f"我的判断是——方向没有争议，节奏才有争议。",
                    "next_speaker": None,
                    "focus": "",
                }, ensure_ascii=False)
            if "开场" in last_user:
                return json.dumps({
                    "type": "question",
                    "content": f"今天我们聊「{topic}」。先别站队，在场几位立场差别很大。"
                               f"我想先问一个最实际的问题：如果现在就动手，谁会先踩到坑？",
                    "next_speaker": "skeptic",
                    "focus": "现在立刻动手，最先踩到的坑是什么？",
                }, ensure_ascii=False)
            return json.dumps({
                "type": "question",
                "content": "刚才这个说法我不太买账——你给的是趋势判断，我要的是代价。"
                           "换个人，从你的专业角度说说，这个判断哪里站得住？",
                "next_speaker": random.choice(["optimist", "builder", "ethicist", "user_advocate"]),
                "focus": "这个判断在实际执行层面站得住吗？",
            }, ensure_ascii=False)

        # 专家：1-2 句短发言（确定性，避免每次刷新内容乱跳）
        name = "我"
        if "你是" in system:
            name = system.split("你是")[1].split("，")[0].strip()
        stance = ""
        if "你的立场：" in system:
            stance = system.split("你的立场：")[1].split("\n")[0].strip()
        focus = last_user.split("当前焦点：")[1].split("\n")[0].strip() if "当前焦点：" in last_user else topic
        seq = len(system) + len(last_user)
        return mock_speech(name, stance or "有自己的独立判断", topic, focus, seq)


def build_client(settings: Settings) -> BaseLLMClient:
    if settings.mock or not settings.deepseek_api_key:
        return MockLLMClient(settings)
    return DeepSeekClient(settings)
