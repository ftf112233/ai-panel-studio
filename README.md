# AI 圆桌讨论 · Web App MVP

一场由多个立场**天然对立**的 AI 嘉宾参与的多轮圆桌讨论：主持人控场、点名发言、追问交锋，最后收敛出总结。
全链路真实流式（SSE），前端可见逐字上屏与"正在思考"动画。

## 快速开始

```bash
# 1) 安装依赖
pip install -r backend/requirements.txt

# 2) 配置 Key（可选：不配也能跑，自动进入 Mock 流式模式）
cp .env.example .env      # 填入 DEEPSEEK_API_KEY

# 3) 启动
python -m uvicorn backend.app.main:app --reload --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

> 启动方式二（推荐）：
> ```
> cd backend && python -m uvicorn app.main:app --reload --port 8000
> ```
> 启动方式三（**零依赖**，未装 fastapi 也能演示，仅用于本地）：
> ```
> python backend/serve.py 8000          # 加 MOCK=true 可强制 Mock 流式
> ```
> 零依赖冒烟（不装 fastapi 也能验证编排链路）：`python backend/smoke.py`
> 单元测试：`python backend/tests/test_orchestrator.py`

## 功能

| 页面 | 说明 |
|---|---|
| 圆桌列表 | 展示全部圆桌及状态（待开始/进行中/已结束/异常） |
| 发起圆桌 | 输入主题 + 选择 2-5 位嘉宾（嘉宾立场已预埋分歧） |
| 直播现场 | SSE 流式上屏、思考动画、轮次分隔、聚焦问题、立场漂移标签、Transcript 侧栏 |
| 历史归档 | 已结束圆桌的完整记录与主持人总结（支持回放式播放） |

## 架构

```
前端(Vanilla JS) ──REST──┐
                         ├─ FastAPI ─ Orchestrator(状态机) ─ HostAgent/GuestAgent ─ DeepSeek(流式)
                  ──SSE──┘                                        └─ 版本化 Prompt(prompts/*.json) + JSON Schema 校验
                                      └─ SQLite(personas/debates/messages)
```

- 状态机：`OPENING → ROUND[1..N]（每轮最多 K 次发言）→ SUMMARY → DONE`
- 调度：**点名制**（主持人给聚焦问题并点名），比自由抢话稳定、重复率低
- 结构化输出：Host 决策整体校验后"分块回放"上屏；Guest 正文纯流式，结束后用一次极短调用标注 `stance_shift`
- 详见 `docs/01-架构设计文档.md`、`docs/02-Prompt设计文档.md`

## 兜底策略（任何单点失败都不中断直播）

| 故障 | 处理 |
|---|---|
| Host 输出非法 JSON | 重试 1 次 → 降级兜底文案 + 调度器备选发言人，前端打"结构降级"标 |
| `next_speaker` 不在场 | 修正为备选发言人 |
| Guest 流式中断/超时 | 已产出部分上屏，不足 20 字补占位句 |
| 轮次/发言数超限 | 强制进入 SUMMARY |
| SSE 断线 | EventSource 自动重连；刷新页面时走存档回放 |
| 顶层异常 | status=failed + error 事件，前端提示可重试 |

## 作业三问

**Q1：使用 Claude Code 结合 DeepSeek V4 进行开发或迭代，如何实现？**
Claude Code（本项目的代码协作者）负责代码生成、重构、写测试与定位报错；DeepSeek 是**运行时**的推理引擎，是被调试的对象而非开发工具。两者角色分离：开发期用 `MockLLMClient` / 测试里的 `StubLLM` 提供假流式响应，让编排逻辑的单元测试不烧 token 也能跑通（`python backend/tests/test_orchestrator.py`）；联调期切真实 DeepSeek 跑冒烟。Prompt 的每次迭代都以 `prompts/*.json` 的 `changelog` 字段落盘进 Git，迭代过程本身可追溯。

**Q2：如何判断多个 Agent 是否真的"有价值"？**
不看"看起来热闹"，看三条可验证指标：① **交锋率**——嘉宾是否引用并反驳了对方的具体论据（人工标注命中/未命中）；② **收敛性**——有限轮次内产出总结，且总结覆盖各方最强论点；③ **立场漂移有据**——`stance_shift=soften/change` 必须伴随被说服的具体原因。用固定 3 主题 × 3 次运行打 `evals/rubric.md` 的评估表，避免单次运气。

**Q3：圆桌流程中最不确定的问题，如何通过实验验证？**
最不确定的是**点名制 vs 自由抢话制**哪个讨论质量更高。实验设计：同一主题、同一组 Persona，两种调度各跑 3 次，用 Q2 的评估表对比"交锋率"与"重复率"。预判点名制交锋率略低但重复率显著更低、整体更稳定，因此 **MVP 先上点名制**；若数据支持，再引入混合模式（主持人可发起"自由回应一轮"）。实验只需改 `Settings.max_speeches_per_round` 与 Host Prompt 的调度约束，不需要改架构。

## 目录

```
backend/  app/(config, main, orchestrator, context, agents/, llm/, storage/)
          prompts/(host.v4.json, guest.v3.json)  tests/  smoke.py
frontend/ index.html  css/  js/
docs/     架构设计 / Prompt 设计 / 工作流程图 / 提交清单
evals/    rubric.md（人工评估表）
```
