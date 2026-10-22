# AI Panel Studio · AI 圆桌演播厅 MVP

输入话题 + 专家人数（默认 4），系统调用大模型**动态生成**主持人 + 专家阵容（姓名 / 职业 / Title / 立场 / 专属颜色），确认后进入演播厅，观看一场实时推进的多轮圆桌讨论：主持人开场、追问、串联、插话、总结；专家**自主**举手 / 补充 / 反驳，每次 1-2 句；过程中实时更新共识与分歧。

仓库：<https://github.com/ftf112233/ai-panel-studio>（私有，按需授权访问）

> 通过压缩包获取源码时，解压后按下面的步骤运行即可，**不需要 GitHub 访问权限**。

## 最快体验（不装依赖、不配 Key）

```bash
python backend/serve.py 8000
```

浏览器打开 <http://127.0.0.1:8000>：

1. 首页选一个预置话题，或自由输入一个主题 → 选专家人数 → 点「生成阵容」
2. 确认阵容后自动进入**演播厅**：主持人开场 → 专家自主举手/补充/反驳（每次 1-2 句）→ 右侧实时刷新「专家状态 / 共识与分歧 / Transcript」
3. 讨论结束由主持人做自然语言总结；到「归档」页可逐字回放任意历史场次

> 未配置 API Key 时自动进入 **Mock 流式模式**（同样逐字上屏，节奏与真实模型一致），完整流程照样可演示。

## 快速开始（正式路径）

```bash
# 1) 安装依赖
pip install -r backend/requirements.txt

# 2) 配置 Key（可选：不配也能跑，自动进入 Mock 流式模式）
cp .env.example .env        # Windows 用：copy .env.example .env
# 在 .env 里填入 DEEPSEEK_API_KEY=sk-xxx

# 3) 启动（生产路径）
cd backend && python -m uvicorn app.main:app --reload --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

一键脚本（建虚拟环境 → 装依赖 → 启动，一条龙）：Windows 双击 `scripts/start.bat`，macOS / Linux 执行 `bash scripts/start.sh`。

> 上面这条 `python backend/serve.py 8000` 走的是**零依赖路径**（未装 fastapi 也能演示 / 跑 E2E，内部用标准库 `http.server` 实现了同一套路由）。想强制 Mock 流式：`MOCK=true python backend/serve.py 8000`。

### 用 PyCharm 运行（可选）

仓库随附 3 个 Run Configuration，打开项目后在右上角下拉里直接选即可：

| 配置名 | 用途 | 工作目录 |
|---|---|---|
| `AI Panel Studio · 零依赖 serve.py` | **不装依赖也能完整演示** | 项目根 |
| `AI Panel Studio · FastAPI(uvicorn)` | 正式路径（需已装 fastapi/uvicorn） | `backend` |
| `Tests · 全部单测(不打网络/不烧token)` | 跑 `backend/tests/` 下全部单测 | `backend` |

前置两步：`File → Open` 打开 `ai-roundtable` 目录本身；右键 `backend` → `Mark Directory as → Sources Root`（否则 `from app.xxx import` 飘红，不影响运行）。要接真模型，在配置的 `Environment variables` 里加 `DEEPSEEK_API_KEY=sk-xxx`，或在项目根放 `.env`。

### 运行排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `Address already in use` / `[Errno 10048]` | 8000 端口被占用 | 换端口：`python backend/serve.py 8111`；FastAPI 路径用 `PORT=8111 python backend/run_uvicorn.py`（Windows：`set PORT=8111 && python backend/run_uvicorn.py`） |
| 运行键**转圈** | 服务正在运行（正常现象） | 浏览器打开对应端口；红色方块 = 停止 |
| 配置左侧出现 **✖** | 解释器未配置，或该配置依赖未安装 | 先用「零依赖 serve.py」配置；接真模型再装依赖 |
| `from app.xxx` 飘红 | 未标记源码根 | 右键 `backend` → `Mark Directory as → Sources Root` |
| 页面一直停在「生成阵容」 | 未配 Key 时走 Mock，或真模型响应慢 | 看后端日志；Mock 模式每场约 60 秒属正常 |

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

## 目录结构

```
ai-roundtable/
├── backend/
│   ├── app/        main.py(FastAPI 路由) · orchestrator.py(状态机) · agents/ · llm/ · storage/
│   ├── prompts/    lineup / host / guest / director / insight *.json（内置 version + changelog）
│   ├── serve.py    零依赖 stdlib 版服务（未装 fastapi 时用同一套路由）
│   ├── tests/      16 个单测        e2e/ 4 个端到端
│   └── smoke.py / smoke_real.py    冒烟脚本（Mock / 真实 API）
├── frontend/       index.html + css/ + js/
├── scripts/        init_db.sql · start.bat · start.sh
└── docs/           需求原文 · 设计 · API · Prompt 记录 · 联调实录 · 逐条验收
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

1. **调度策略实验**：固定 3 个主题 × 每种调度跑 3 次，按「交锋率 / 重复率 / 聚焦度 / 收敛性 / 立场真实性 / 人设一致性」6 个指标（0-2 分）人工打分，用数据决定默认调度策略
2. **共识/分歧质量**：当前靠一次 LLM 提炼，后续可做多轮投票式聚合与置信度
3. **持久化与并发**：SQLite 单文件在多人同时观看时够用，但事件流目前靠 SSE 重放；可引入事件表 + 断点续传（Last-Event-ID）
4. **用户干预**：允许观众中途提问或"指定下一位发言人"
5. **可观测性**：记录每次 LLM 调用的 token/耗时/降级率，形成质量看板

## 交付物

| 交付物 | 位置 |
|---|---|
| 可运行源码 | 本仓库（GitHub 私有，按需授权）；亦可以压缩包形式交付 |
| 架构设计文档（模块图 / 接口 / 数据流 / 兜底） | `docs/01-架构设计文档.md`、`docs/10-PRD.md`、`docs/11-ER图.md`、`docs/12-API文档.md` |
| Prompt 设计文档 + Prompt 记录（含版本迭代） | `docs/02-Prompt设计文档.md`、`docs/13-Prompt记录.md`、`backend/prompts/*.json` |
| 工作流程图 | `docs/00-工作流程图.md`（含运行时数据流、状态机、Git 分支流程） |
| 需求逐条验收 + 真实联调实录 | `docs/16-需求逐条验收.md`、`docs/15-真实联调实录.md` |

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/00-作业需求原文.md` | 作业原文（存档备查） |
| `docs/10-PRD.md` | PRD（含 mermaid 流程图与状态机） |
| `docs/11-ER图.md` | ER 图 + 建模决策 |
| `docs/12-API文档.md` | REST + SSE 契约 |
| `docs/13-Prompt记录.md` | ≥5 段核心 Prompt，SDD/DDD/TDD/E2E 四阶段标记 |
| `docs/14-开发过程与工作流说明.md` | 开发流程、3 个典型问题、工程化理解 |
| `docs/01-架构设计文档.md` / `docs/02-Prompt设计文档.md` / `docs/00-工作流程图.md` | 早期设计稿与迭代记录 |
| `docs/15-真实联调实录.md` | 真实 DeepSeek API 跑通的两场完整实录 |
| `docs/16-需求逐条验收.md` | 功能要求 / 技术要求 / 核心考察点逐条对照 |
