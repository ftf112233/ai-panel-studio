# AI Panel Studio · AI 圆桌演播厅 MVP

输入话题 + 专家人数（默认 4），系统调用大模型**动态生成**主持人 + 专家阵容（姓名 / 职业 / Title / 立场 / 专属颜色），确认后进入演播厅，观看一场实时推进的多轮圆桌讨论：主持人开场、追问、串联、插话、总结；专家**自主**举手 / 补充 / 反驳，每次 1-2 句；过程中实时更新共识与分歧。

仓库：<https://github.com/ftf112233/ai-panel-studio>（私有）

## 快速开始

```bash
# 1) 安装依赖
pip install -r backend/requirements.txt

# 2) 配置 Key（可选：不配也能跑，自动进入 Mock 流式模式）
cp .env.example .env        # 填入 DEEPSEEK_API_KEY

# 3) 启动（生产路径）
cd backend && python -m uvicorn app.main:app --reload --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

**零依赖启动**（未装 fastapi 也能演示 / 跑 E2E）：

```bash
python backend/serve.py 8000          # MOCK=true 可强制 Mock 流式
```

### 用 PyCharm 运行（本机推荐）

1. **打开项目**：`File → Open` 选择 `ai-roundtable` 目录（不是它的父目录）。
2. **解释器**：`Settings → Python Interpreter` 选 Python 3.10+；在 Python Packages 面板里装 `fastapi` `uvicorn` `httpx`（或 Terminal 执行 `pip install -r backend/requirements.txt`）。
3. **标记源码根**：右键 `backend` 目录 → `Mark Directory as → Sources Root`（否则 `from app.xxx import` 会飘红，运行不受影响）。
4. **选一个 Run Configuration**（已随仓库提供，右上角下拉即可看到）：

| 配置名 | 用途 | 工作目录 |
|---|---|---|
| `AI Panel Studio · 零依赖 serve.py` | **不装 fastapi 也能跑**，适合先看效果 | 项目根 |
| `AI Panel Studio · FastAPI(uvicorn)` | 正式路径（需已装依赖） | `backend` |
| `Tests · 核心逻辑(不打网络/不烧token)` | 跑 `tests/test_core.py` | `backend` |

5. **填 Key**（可选）：在对应 Run Configuration 的 `Environment variables` 里加 `DEEPSEEK_API_KEY=sk-xxx`；不填就自动进入 Mock 流式。也可以直接在项目根放 `.env`（已被 gitignore）。
6. 点绿色三角运行，浏览器打开 **http://127.0.0.1:8000**。

> 若不装任何依赖，只用第 1 个配置即可完整演示（首页 / 发起 / 演播厅 / 归档全部可用）。
> PyCharm 的 Terminal 里也可以用命令行，见下。

### PyCharm 运行排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 运行键**转圈** | 服务正在运行（这是正常的！） | 浏览器打开 <http://127.0.0.1:8000>；红色方块 = 停止 |
| 配置左侧出现 **✖** | ① 解释器没配置好；② 该配置需要的依赖没装（FastAPI 那个需要 fastapi/uvicorn） | 先用「零依赖 serve.py」配置跑；要接真模型再装依赖 |
| 所有配置都 ✖ | 没有配置 Python 解释器 | `Settings → Project → Python Interpreter → Add Interpreter` 选本机 Python |
| 装依赖 | Terminal 里执行 | `pip install -r backend/requirements.txt` |
| `from app.xxx` 飘红 | 未标记源码根 | 右键 `backend` → `Mark Directory as → Sources Root` |

其他命令：

```bash
python backend/smoke.py                       # 零依赖冒烟：跑完整一场
python backend/tests/test_core.py             # 核心逻辑单测（阵容/调度/共识）
python backend/tests/test_orchestrator.py     # 编排器单测（状态机/非轮流/状态小窗）
python backend/e2e/test_e2e.py                # E2E：起服务 → 双讨论并行隔离验证
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 为空自动进入 Mock 流式；**只存在后端 env，绝不下发浏览器** |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `MOCK` | 空 | `true` 强制 Mock |
| `MAX_ROUNDS` | 4 | 轮数上限 |
| `MAX_SPEECHES_PER_ROUND` | 4 | 每轮发言次数上限 |
| `DB_PATH` | `backend/data/roundtable.db` | SQLite 路径 |

## 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3 + FastAPI（+ uvicorn） | 异步 SSE 支持好；同时提供等价的 stdlib `http.server` 版，保证离线可演示 |
| 数据 | SQLite（标准库 sqlite3） | 作业指定；零运维，初始化脚本 `scripts/init_db.sql` |
| 前端 | 原生 HTML/CSS/JS（无框架） | 演播厅布局靠 CSS Grid 即可精确控制"区域独立滚动"，避免框架带来的体积与构建 |
| 实时 | SSE（EventSource） | 单向推送足够；比 WebSocket 简单，断线自动重连 |
| 模型 | DeepSeek（OpenAI 兼容协议） | 国内可用、成本低；缺 Key 时自动降级 Mock 流式 |
| 测试 | unittest + asyncio（零第三方依赖） | 沙箱/离线可跑；桩 LLM 可脚本化模拟异常 |

## 主要 API 列表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 + 当前模式 |
| GET | `/api/topics` | ≥5 条样例数据（话题 + 阵容） |
| POST | `/api/lineups` | 大模型动态生成阵容 `{topic, expert_count}` |
| POST | `/api/debates` | 确认阵容后建单 `{topic, lineup}` |
| GET | `/api/debates` | 讨论列表 |
| GET | `/api/debates/{id}` | 详情（messages / consensus / disagreements / summary） |
| GET | `/api/debates/{id}/stream` | SSE 事件流（直播 / 已结束则逐字回放） |

SSE 事件：`participants` `round_change` `focus` `agent_status` `speaker_start` `delta` `speaker_end` `stance` `insight` `error` `done` —— 详见 `docs/12-API文档.md`。

## 架构

```
浏览器(原生 JS) ──REST──┐
                        ├─ FastAPI ── Orchestrator(状态机)
                 ──SSE──┘                ├─ HostAgent     开场/串联/追问/插话/总结
                                         ├─ DirectorAgent 自主调度(举手/补充/反驳)+公开思考摘要
                                         ├─ GuestAgent    1-2 句流式发言 + 立场漂移
                                         ├─ InsightAgent  共识/分歧增量提炼
                                         └─ LineupAgent   动态生成阵容
                                         └─ SQLite(topics / debates / messages)
```

- 状态机：`OPENING → ROUND[1..N] → SUMMARY → DONE`
- **禁止机械轮流**：`DirectorAgent` 依据 transcript 选人，且绝不会连续选同一个人（有单测断言）
- 结构化输出：决策类（Host/Director/Insight）用 JSON 整体校验后再推正文；专家正文纯流式。页面永远只显示自然语言，**不显示 JSON 原文**

## 真实 DeepSeek 联调记录（非 Mock）

```bash
DEEPSEEK_API_KEY=sk-xxx python backend/smoke_real.py   # 默认 1 轮 / 2 次发言，省 token
```

实测输出（deepseek-chat，真实生成，未作任何修饰）：

- **阵容生成**：李锋（某电商平台技术VP，主导过两次 AI 辅助编程工具全团队推广）／王冉（开源项目 Maintainer，带过五届校招新人）／赵敏（中型软件公司 CHO，负责过三轮校招缩编）／孙哲（高校计算机系副教授，参与过课程改革）——四人身份具体到可反驳。
- **讨论**：`[举手]` 李锋 → `[反驳]` 王冉（调度器自主选人，非轮流）。
- **共识/分歧**（真实提炼）：共识「不应一刀切，应按岗位区别对待」「协作岗应每周回办公室两到三天」；分歧「李锋 vs 王冉：岗位缩减一半还是工作内容转向调试与需求理解」。
- **总结**：主持人点出真分歧、各方最强论点（"人才成长阶梯就断了"）与可执行下一步。

> 说明：无 API Key 时自动进入 Mock 流式；装了 httpx 走 httpx，**没装 httpx 会自动改用标准库 urllib 流式**，因此零依赖也能接真模型。
> 完整实录（含两场真实讨论的发言顺序、共识分歧、总结原文）见 `docs/15-真实联调实录.md`。

## 需求对照（作业 F1-F12）

| 需求 | 实现 |
|---|---|
| 首页列表 + 加入观察 | ✅ `#/` |
| LLM 动态生成阵容 + 确认 | ✅ `#/create` → 生成 → 确认 |
| 自主发言调度（举手/补充/反驳） | ✅ DirectorAgent |
| 每次 1-2 句 | ✅ guest.v4 + 120 字打断 |
| 专家状态小窗 | ✅ 右侧面板（待机/准备发言/发言中 + 公开思考摘要） |
| 实时共识与分歧 | ✅ 每条发言后增量更新 |
| Transcript（姓名+职业/Title+色块） | ✅ 右侧面板，不显示内部事件 |
| 主持人自然语言总结 | ✅ |
| Key 仅后端 env | ✅ |
| 多讨论并行隔离 | ✅ E2E 验证 |
| SSE | ✅ |
| 中文 UI / 区域独立滚动 / 响应式 | ✅ 三档断点（>1600 / 1080 / <720） |

## 兜底策略（任何单点失败都不中断直播）

| 故障 | 处理 |
|---|---|
| 阵容生成返回非法 JSON | 重试 1 次 → 内置嘉宾池补全（保证人数与颜色不重复） |
| Host / Director 输出非法 | 降级兜底文案 + 确定性补位（发言次数最少者优先） |
| 专家流式中断 | 已产出部分上屏，不足则补占位句 |
| 专家发言过长 | 主持人插话打断并要求给结论 |
| Insight 调用失败 | 沿用上一次结果，讨论继续 |
| 轮次/发言数超限 | 强制进入总结 |
| SSE 断线 | EventSource 自动重连；刷新走存档逐字回放 |
| 顶层异常 | `status=failed` + error 事件，前端提示可重试 |

## 已完成能力

- 动态阵容生成与确认、演播厅直播、自主调度、1-2 句短发言、主持人插话
- 专家状态小窗、实时共识/分歧、Transcript、自然语言总结、历史归档回放
- 多讨论并行隔离、零依赖演示服务、16 个单测 + 4 个 E2E

## 后续改进方向

1. **调度策略实验**：点名制 vs 自由抢话的 A/B 评估（`evals/rubric.md` 已有 6 指标评估表），用数据决定默认策略
2. **共识/分歧质量**：当前靠一次 LLM 提炼，后续可做多轮投票式聚合与置信度
3. **持久化与并发**：SQLite 单文件在多人同时观看时够用，但事件流目前靠 SSE 重放；可引入事件表 + 断点续传（Last-Event-ID）
4. **用户干预**：允许观众中途提问或"指定下一位发言人"
5. **可观测性**：记录每次 LLM 调用的 token/耗时/降级率，形成质量看板

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/00-作业需求原文.md` | 作业原文 + 验收点对照 |
| `docs/10-PRD.md` | PRD（含 mermaid 流程图与状态机） |
| `docs/11-ER图.md` | ER 图 + 建模决策 |
| `docs/12-API文档.md` | REST + SSE 契约 |
| `docs/13-Prompt记录.md` | ≥5 段核心 Prompt，SDD/DDD/TDD/E2E 四阶段标记 |
| `docs/14-开发过程与工作流说明.md` | 开发流程、3 个典型问题、工程化理解 |
| `docs/01-架构设计文档.md` / `docs/02-Prompt设计文档.md` / `docs/00-工作流程图.md` | 早期设计稿与迭代记录 |
| `evals/rubric.md` | 圆桌质量人工评估表 |
