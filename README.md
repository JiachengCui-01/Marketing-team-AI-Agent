# Marketing Agent · 企业营销团队 AI 工作台

> 面向企业营销团队的**多智能体 AI 工作台**：一个入口里既有「内容 / 分析 / 研究」营销专家协作，又有「审批 / 任务 / 日程 / 知识问答」的 OA 助手，外加实时 IM 消息与通讯录协同 —— **全过程可追踪、写操作先草稿后确认、结果持久化兜底**。

---

## 1. 项目背景

企业营销团队的日常被割裂在一堆工具里：写多平台文案、分析投放数据、做竞品与行业研究，还要处理请假/报销审批、任务派发、会议日程、查内部制度文档 —— 上下文频繁切换，效率低。

而通用 AI 聊天工具用于团队办公时有三个硬伤：

- **黑箱**：看不到 AI 每一步在做什么，出了结果也难以信任。
- **易幻觉、易越权**：一个模型既写文案又"算"指标又"声称"外部事实，容易编造。
- **写操作有风险、结果易丢**：直接执行"已提交审批 / 已创建日程"却无人确认；流式连接一断，结果就没了。

**Marketing Agent** 把「营销专家团队 + 企业 OA 助手 + 实时协同」整合进**一个可追踪、可兜底、先确认后执行**的工作台。

## 2. 产品目标

| 目标 | 做法 |
| --- | --- |
| 一个入口完成 **营销 + 办公 + 协同** | 编排器统一调度营销专家与 OA 工具，侧边栏聚合消息/通讯录/审批/任务/日历/新闻/图像 |
| 过程**可见**、结果**可兜底** | 右侧 Agent Trace 实时展示编排步骤；产出物（文案 PDF / 图片 / 摘要）落库持久化 |
| 写操作 **human-in-the-loop** | 审批 / 任务 / 日程一律"先出草稿卡 → 用户确认 → 才落库" |
| **企业级** 多人协作 | 组织 + 邀请码、组织内/外部通讯录、实时 IM（人↔人 / 群）、用户级数据隔离与权限 |

## 3. 核心功能

- **营销多智能体对话**：编排器（chief of staff）按需分派 **内容 / 分析 / 研究** 三类专家，综合成带引用的最终回答，必要时产出 PDF。
- **Agent Trace 追踪 + 预览面板**：右栏两个标签 —— `追踪` 实时显示 intake→planning→delegating→synthesis 每一步；`预览` 以**浏览器式多标签**内联打开产出物、上传件、被引用的网页与知识库文档。
- **企业 OA 助手（对话即可发起）**：审批（请假/报销/采购/通用）、任务待办、日程日历、知识问答 —— 全部通过聊天用自然语言发起，AI 生成**草稿卡**，用户点确认后才真正写入。
- **知识库 RAG**：上传文档 → 检索 → 回答附**来源引用**，点击引用可在预览区打开原文（embedding → reranker → 词法多级检索，缺重依赖时自动降级）。
- **行业新闻自动摘要**：配置每日行业/主题、简报或详报、推送时间与时区，定时抓取并生成**分级来源**摘要，可手动刷新、可撤销回滚。
- **营销图 AI 生成**：文生图（Gemini）、上传参考图、一键抠图去背景、按平台风格（淘宝 / 小红书 / 亚马逊 / Instagram）套模板画布合成、生成历史与再编辑。
- **实时协同**：IM 消息（人↔人 / 群聊、未读数、已读回执、文件消息，基于 SSE 实时推送）+ 通讯录（组织成员 / 外部联系人 / 联系人申请 / 星标 / 我的群组）。
- **账户与个性化**：注册登录、组织与邀请码、可解释且可关闭的**营销记忆**（自动学习你的品牌/渠道偏好，附证据台账）。

## 4. 产品架构

三层结构，编排与执行解耦：

```text
┌────────────────────────────────────────────────────────────────┐
│  Next.js 14 前端（单页工作台 web/app/page.tsx）                 │
│  左：会话/导航   中：对话 & 各功能面板   右：预览 / Agent Trace  │
└───────────────▲───────────────────────────────┬────────────────┘
                │ SSE 事件流（追踪/增量/草稿/产出）│ REST /api
┌───────────────┴───────────────────────────────▼────────────────┐
│  FastAPI 后端（server/）   streaming.py 同步→异步 SSE 桥         │
│  routes.py 全量 /api 端点   auth.py 认证   db.py SQLite 数据层    │
└───────────────▲────────────────────────────────────────────────┘
                │ 进程内调用
┌───────────────┴────────────────────────────────────────────────┐
│  多智能体核心（src/marketing_agent/，Anthropic Claude SDK）      │
│                                                                  │
│   Orchestrator / OA Copilot  ── 任务控制层（不直接干活）         │
│        ├─ delegate → 内容 Agent（多平台文案 + PDF）              │
│        ├─ delegate → 分析 Agent（Files API + 代码沙箱算指标）    │
│        ├─ delegate → 研究 Agent（web_search + 分级来源）         │
│        └─ OA 工具：draft_approval / draft_task / draft_event /   │
│                    query_* / search_knowledge_base              │
└─────────────────────────────────────────────────────────────────┘
```

- **编排器（`orchestrator.py`）**：tool-use 循环（最多 12 轮），并行分派专家、再综合为 markdown。硬约束：**它自己不写文案、不算指标、不声称外部事实**，一律通过 delegate 工具下派，避免越权与幻觉。
- **OA Copilot（`oa/agent.py`）**：聊天实际运行者，复用编排器的分派/流式机制，额外挂载 OA 工具，一个助手同时覆盖办公流程与营销分派。
- **三类专家（`agents/`）**：内容（渠道 SOP 技能）、分析（数据不进 prompt，上传到 Files API 在沙箱里跑 pandas 算 CTR/CVR/ROAS）、研究（服务端 web_search + `source_scoring` 分级）。

## 5. 典型任务流程示例：
**场景 A · 研究 → 分析 → 文案（一句话完成一条营销链路）**
用户："帮我调研下竞品近期的投放打法，结合我们上周的投放数据，写 3 条小红书文案。"
→ 编排器 `intake/planning` → 并行 `delegating` 研究 Agent（web_search 查竞品）+ 分析 Agent（跑上周数据）→ `specialist_done` → 内容 Agent 产出文案 → `synthesis` 汇总为带**来源引用**的回答（含竞品简报 PDF）。全过程在右侧 Trace 可见。

**场景 B · 对话式办公（请假 / 排会，草稿→确认）**
用户："生成日程"
→ OA 生成**日程草稿卡**（时区感知）→ 用户核对时间点「确认创建」→ 才落库、日历中出现。审批、任务同理，AI 从不擅自"已提交"。
<img width="1280" height="697" alt="image" src="https://github.com/user-attachments/assets/d617f699-e0fa-4554-a6d2-a70707c2069a" />
手动确认后，同步到日程中，并在顶部导航栏提供今日最近日程的预览：
<img width="1278" height="698" alt="image" src="https://github.com/user-attachments/assets/03ca47b3-d336-4953-9a38-c14e75bf425c" />
<img width="1280" height="698" alt="image" src="https://github.com/user-attachments/assets/52cfdcf5-701c-46e0-82e0-b3bce5cc805f" />
审批流程展示：
<img width="1280" height="692" alt="image" src="https://github.com/user-attachments/assets/bb2235af-24bb-4fde-a52a-b38538289d08" />
<img width="1280" height="698" alt="image" src="https://github.com/user-attachments/assets/fe9ac547-fcc0-4bcb-aa75-b12c87f3e585" />

**场景 C · 知识问答（内部制度秒查，来源可溯）**
用户："公司的报销制度、额度和流程是什么？"→ 检索知识库 → 回答附**来源 capsule** → 点引用在预览区直接打开原始文档。
<img width="1280" height="696" alt="image" src="https://github.com/user-attachments/assets/c109cf91-f21c-4d96-9cec-7ee9bf53ad1b" />

**场景 D · 行业新闻日报**
配置每日行业摘要（行业、简报/详报、时间、时区）→ 定时抓取 → 生成**分级来源**摘要推送，可手动"立即刷新"。
<img width="1280" height="695" alt="image" src="https://github.com/user-attachments/assets/88e46ffb-2791-4837-a753-7297b00e8960" />
可配置自动总结的内容主题、详细程度、自动推送时间：
<img width="1280" height="696" alt="image" src="https://github.com/user-attachments/assets/ca727eac-7a5b-4e68-bf43-7386390a71ec" />
<img width="1280" height="696" alt="24 小时行业新闻自动收集与摘要" src="https://github.com/user-attachments/assets/ae1832b2-a6f0-4512-913e-05ffad7062e9" />

**场景 E · 营销图生成**
上传产品图 → 可选是否一键抠图 → 可以选平台模板（小红书/淘宝/亚马逊/Instagram）/或者直接在下方输入栏输入需求→ 生成 → 历史与再编辑。
<img width="1277" height="696" alt="image" src="https://github.com/user-attachments/assets/5cc04a40-1da3-494a-b387-9546e428ffa4" />
模板生成：
<img width="1280" height="695" alt="image" src="https://github.com/user-attachments/assets/647dafdf-f86a-4384-94c9-81a84c50f9d2" />
生成后二次AI编辑生成和手动细节修改：
<img width="1280" height="692" alt="image" src="https://github.com/user-attachments/assets/a4807f17-3e66-44a0-9d1f-59fb4dec830f" />
历史生成记录查看：
<img width="1280" height="694" alt="image" src="https://github.com/user-attachments/assets/4d3bbb8a-5d58-43e7-a4a1-0f13a5068f03" />

**场景 F · 实时协同**
IM 消息（人↔人 / 群聊、未读数、已读回执、文件消息，基于 SSE 实时推送）+ 通讯录（组织成员 / 外部联系人 / 联系人申请 / 星标 / 我的群组）。
<img width="1280" height="697" alt="image" src="https://github.com/user-attachments/assets/e8335873-19bd-4bcb-906b-2fb580c59c38" />
<img width="1275" height="700" alt="image" src="https://github.com/user-attachments/assets/5899b403-5292-44ea-9f5f-01eb4bbd4a1c" />

**场景 G · 个性化**
可个性化设置系统主题、管理个人记忆、知识库以及个人画像自定义。
<img width="1280" height="694" alt="image" src="https://github.com/user-attachments/assets/de1c2b72-04d1-4d0c-886f-3496077f89a7" />


## 6. 技术栈

**后端 / Agent（`pyproject.toml`）**
- `anthropic`（Claude SDK）—— 编排器、专家、OA copilot、视觉、代码执行、web_search
- `fastapi` + `uvicorn[standard]` —— API / ASGI；`sse-starlette` —— SSE 流式
- `google-genai` —— Gemini 文生图；`Pillow` + `rembg` + `onnxruntime` —— 抠图去背景
- `pypdf` + `python-docx` —— 文档抽取；`reportlab` —— PDF 产出
- `python-multipart`（上传）、`typer` + `rich`（CLI）、`python-dotenv`
- 可选 `semantic` extra：`sentence-transformers`（本地 embedding，缺失时降级词法检索）

**前端（`web/package.json`）**
- `next@14`（App Router）、`react@18`、`tailwindcss@3`
- `react-markdown` + `remark-gfm`（markdown / 引用渲染）、`lucide-react`（图标）、`next-themes`（深色模式）

**数据与基础设施**
- SQLite（WAL、外键、`MARKETING_AGENT_DB_PATH` 可配）
- 后端 Render（持久磁盘挂 SQLite 与 rembg 权重）、前端 Vercel

## 7. AI Coding 开发过程

本项目**从架构到实现由 Claude Code（Opus）全程驱动**开发，工作流固定为一个闭环：

`Plan Mode 规划 → 实现 → 浏览器实测验证（SSE/交互/回归）→ 提交 → 部署`

- **迭代路线**：MVP 营销多智能体 → 引入 OA Copilot（审批/任务/日程/知识库、草稿-确认）→ 企业协同（IM 消息 + 通讯录）→ 体验打磨（引用点开预览、编辑消息重新生成、停止生成、日程时区修正）。
- **智能体本身也基于 Anthropic SDK**：编排器 `high` effort、专家 `medium`，另用轻量 `claude-haiku-4-5` 做记忆抽取与澄清，成本与质量分层。
- 每次改动都在真实浏览器里验证（读取控制台/网络/SSE、点选交互），而非仅跑单测。

## 8. 可信、安全与异常设计

- **草稿 → 确认（human-in-the-loop）**：所有写操作（审批/任务/日程）**永不由模型直接持久化**，先以 `oa_draft` 事件渲染确认卡，用户点确认才命中对应 `POST` 端点；系统提示词禁止模型声称"已提交/已创建"。草稿在前端本地留存，刷新不丢。
- **过程可追踪**：编排/专家生命周期以 SSE 事件（`started` / `orchestrator_step` / `delegating` / `specialist_done` / `assistant_delta` / `artifact_created` / `result`）实时呈现在 Agent Trace。
- **认证与权限**：PBKDF2-SHA256（20 万轮、每用户盐、常量时间比较）、Bearer Token（14 天 TTL）；注册校验中国身份证校验位与邮箱/手机号；对外投影**脱敏**身份证、绝不返回密码哈希。所有受保护路由经 `require_user`，数据读取按 `user_id` 隔离；知识库文档带 `scope`（个人/组织）校验成员，IM 文件下载校验会话成员。
- **优雅降级**：专家不可用时返回 `## …Unavailable` 的 markdown 而非抛错；图像生成永不崩；KB 检索 embedding→reranker→词法逐级降级；**流式失败自动回退** `/complete` 再恢复会话记录，避免结果丢失。
- **时区与时间**：日历存 epoch 瞬时、拒绝过去时间（120s 偏差容忍）、按用户时区调度新闻；OA 提示词注入当前本地时间以正确解析"明天/周五"。
- **反越权 / 反幻觉**：编排器被硬性约束不写文案、不算指标、不编造外部事实，只能下派。

## 9. 测试与评测

- **后端**：`pytest`，约 180 个用例覆盖 API、会话/记忆、审批/任务/日历、IM/组织/通讯录、图像、新闻、KB 检索、来源评分、OA 工具与 copilot、澄清、记忆抽取、PDF。
  - 代表：`test_routes.py`(41) · `test_image.py`(23) · `test_news.py`(17) · `test_sessions.py`(16) · `test_oa_modules.py`(12) · `test_source_scoring.py`(10) · `test_im.py`(9) · `test_approvals.py`(8) · `test_kb_retrieval.py`(6)。
- **前端**：`tsc --noEmit` 类型检查 + 生产 `next build`。
- **运行**：
  ```bash
  pytest tests -q
  ```
  （测试用独立 DB，设置 `MARKETING_AGENT_DB_PATH` 到临时路径、`ANTHROPIC_API_KEY=test-key`、`MARKETING_AGENT_MEMORY_LLM=0`。）

## 10. 快速开始

**前置**：Python 3.11+、Node 18+、`ANTHROPIC_API_KEY`（必需）、`GEMINI_API_KEY`（营销图功能）。

```bash
# 1) 后端
cp .env.example .env          # 填入 ANTHROPIC_API_KEY / GEMINI_API_KEY
pip install -e .
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000

# 2) 前端（另开终端）
cd web
npm install
echo "NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000" > .env.local   # 指向本地后端
npm run dev                    # http://localhost:3000
```

打开 `http://localhost:3000` 注册账号即可使用。也可用命令行：

```bash
marketing-agent --help         # 内置 CLI（内容/分析/研究）
```

## 11. 项目结构

```text
src/marketing_agent/          Agent 核心（可安装包 + CLI 入口）
  orchestrator.py             营销"chief of staff"编排循环
  oa/agent.py, oa/tools.py    企业 OA copilot + 草稿/查询工具
  agents/                     content / analytics / research 专家 + base、技能
  tools/                      delegation_tools、image_gen(Gemini)、pdf_tool
  config.py, source_scoring.py, conversation.py, memory*.py
server/                       FastAPI 后端
  main.py                     应用工厂、CORS、新闻定时任务
  routes.py                   全部 /api 端点        db.py  SQLite 结构与数据访问
  streaming.py                同步回调 → 异步 SSE 桥  auth.py  密码/令牌/资料校验
  kb_retrieval.py, reranker.py, embeddings.py, query_rewrite.py   KB RAG 管线
  news.py, memory*.py, clarify.py, im_hub.py, uploads.py, image_*.py
web/                          Next.js 14 前端
  app/page.tsx                单页工作台外壳 + SSE 处理
  components/*.tsx            各功能面板 + chat/preview/auth UI
  lib/*                       api、sse、i18n、stores(sessions/im)、oa-drafts
tests/                        pytest 套件（见 §9）
skills/                       营销 SOP 技能（竞品定位简报、产品发布战役）
data/sample_campaign.csv      分析示例输入
render.yaml · vercel.json     部署配置
```

## 12. 当前进度与后续规划

**已完成**
- 营销多智能体编排（内容/分析/研究）+ Agent Trace + 预览多标签
- 企业 OA Copilot：审批 / 任务 / 日程 / 知识问答（对话发起 + 草稿-确认）
- 企业协同：实时 IM（人↔人/群、已读回执、文件）+ 通讯录（组织/外部/星标/群组）
- 营销图 AI 生成、行业新闻自动摘要、可解释营销记忆
- 体验：引用点开预览、编辑历史消息重新生成、停止生成、日程时区修正

**后续规划**
- 审批路由升级：逐级主管（汇报线）+ 按金额/类型的**分级授权矩阵**、会签/或签、加签/转审
- 知识库组织级共享与权限增强、检索质量评测集
- 传输层可选 WebSocket 替代 SSE（双向、断线更平滑）；多 worker 时用 Redis 做 IM pub/sub
- 移动端适配与更多平台图像模板

## 13. 项目复盘

- **收获**：跑通了"编排器 + 多专家"的多智能体协作、SSE 流式与 Agent Trace、human-in-the-loop 的草稿-确认范式、RAG 检索与来源分级，以及一套"AI Coding + 浏览器实测"的开发闭环。
- **关键权衡**：
  - **SSE vs WebSocket**：本项目是"服务器→客户端"单向推送（追踪/增量/草稿），SSE 更轻、自动重连、走标准 HTTP，故选 SSE；IM 也复用同一套。真正需要双向低延迟（如输入中状态）时可升级 WebSocket。
  - **单进程 pub/sub**：`im_hub` 用进程内内存 hub，简单够用；水平扩展需换 Redis。
  - **本地 embedding 可选**：`sentence-transformers` 依赖重，设为可选并对检索做多级降级，保证无 GPU 环境也能跑。
- **不足与改进**：审批路由目前是单级 MVP；KB 组织级共享待增强；完善系统功能，如后续获得许可和企业数据后，加入AI化的BI与客户成功功能。

---

> 部署：后端 Render（`render.yaml`，持久磁盘挂 SQLite / rembg 权重）；前端 Vercel（`vercel.json`，构建 `web/`）。
