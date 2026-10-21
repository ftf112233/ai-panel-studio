# API 文档

Base URL：`http://127.0.0.1:8000`
所有响应 `Content-Type: application/json; charset=utf-8`；SSE 为 `text/event-stream`。

## 1. REST

| 方法 | 路径 | 说明 | 请求体 | 响应要点 |
|---|---|---|---|---|
| GET | `/api/health` | 健康检查 + 当前模式 | — | `{ok, mode:"mock"\|"deepseek", model}` |
| GET | `/api/topics` | 样例数据（≥5 条话题 + 阵容） | — | `[{id, topic, lineup}]` |
| POST | `/api/lineups` | 大模型动态生成阵容 | `{topic, expert_count(2-5)}` | `{topic, lineup:{host, experts[]}}` |
| POST | `/api/debates` | 创建讨论（确认阵容后） | `{topic, lineup}` | `{id, topic, status, expert_count, lineup}` |
| GET | `/api/debates` | 讨论列表（首页） | — | `[{id, topic, status, round, message_count, experts[], summary}]` |
| GET | `/api/debates/{id}` | 讨论详情（归档/回放） | — | `{…, lineup, messages[], consensus[], disagreements[], summary}` |
| GET | `/api/debates/{id}/stream` | **SSE 事件流**（直播/回放） | — | 见下表 |

### 专家对象 `expert`

```json
{"id":"e1","name":"林一舟","occupation":"AI 开发者工具","title":"AI 编程产品创始人",
 "stance":"三年内初级岗位需求会明显萎缩","style":"语速快、爱用类比","color":"#e8590c","avatar":"林"}
```

### 错误约定

| 状态码 | 场景 |
|---|---|
| 400 | 主题少于 2 字 / 阵容少于 2 位专家 / 非法 JSON |
| 404 | 讨论不存在 |
| 500 | 未捕获异常（返回 `{detail}`） |

## 2. SSE 事件协议

每条消息格式：`data: {json}\n\n`

| event | data | 用途 |
|---|---|---|
| `participants` | `{debate_id, topic, host, guests[]}` | 初始化演播厅与色块 |
| `round_change` | `{round, focus}` | 轮次分隔 |
| `focus` | `{focus}` | 当前聚焦问题 |
| `agent_status` | `{speaker_id, status: standby\|preparing\|speaking, thought}` | **专家状态小窗**（thought 为公开思考摘要，非 CoT） |
| `speaker_start` | `{speaker, name, occupation, title, color, action, action_label, interrupt?}` | 开始一条发言 |
| `delta` | `{speaker, text}` | 流式增量（逐字上屏） |
| `speaker_end` | `{speaker, interrupted}` | 发言结束 |
| `stance` | `{speaker, name, shift: hold\|soften\|change}` | 立场漂移标注 |
| `insight` | `{consensus[], disagreements[{a,b,point}]}` | 实时共识与分歧 |
| `error` | `{message, recoverable}` | 异常提示 |
| `done` | `{debate_id, summary, replay?}` | 结束（含主持人自然语言总结） |

说明：
- **`action`（举手/抢答/补充/反驳）只在 `speaker_start` 的结构字段里，不会作为"内部事件"文本出现在 Transcript**（需求 F7）。
- 已结束的讨论再次连接 SSE 时会走**回放路径**：逐字重放 transcript + 先发一次 `insight`，最后 `done.replay=true`。
- 客户端（EventSource）断线会自动重连；`done` 后前端主动 `close()`。

## 3. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 为空时自动进入 Mock 流式模式 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `MOCK` | 空 | `true` 强制 Mock |
| `MAX_ROUNDS` | 4 | 讨论轮数上限 |
| `MAX_SPEECHES_PER_ROUND` | 4 | 每轮发言次数上限 |
| `DB_PATH` | `backend/data/roundtable.db` | SQLite 路径 |
