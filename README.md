# 家居出海工作台 · 大件家具 DTC 的多智能体 AI 系统

> 面向**自主设计大件家具、找供应商代工、以 DTC 方式卖到美国**的外贸团队：一个入口里既有「Listing / 数据 / 市场」三类专家协作，又有「任务 / 日程 / 资料问答」的办公助手，还有定时跑的「自动化」分析，外加实时 IM 消息与通讯录协同 —— **全过程可追踪、写操作先草稿后确认、实物参数绝不编造**。

---

## 1. 项目背景

做美国市场的家具外贸，日常被割裂在一堆工具和时区里：写 Amazon / Wayfair listing 和独立站商详、拍图配图、算广告与退货数据、盯竞品和平台政策，还要派任务、约会议、翻产品规格书和供应商资料 —— 上下文频繁切换，效率低。

而通用 AI 聊天工具用在这门生意上有四个硬伤：

- **黑箱**：看不到 AI 每一步在做什么，出了结果也难以信任。
- **易幻觉、易越权**：一个模型既写文案又"算"指标又"声称"外部事实，容易编造。
- **不懂这个品类**：通用工具会把大件家具当成一般消费品 —— 给沙发写 B2B 帖、给床架做"手持展示"图、只盯 CTR/CVR 而忽略 ACOS 和退货率。
- **写操作有风险、结果易丢**：直接执行"已创建日程 / 已派任务"却无人确认；流式连接一断，结果就没了。

尤其是幻觉这一条，在大件家具上代价不对称：**一个编错的尺寸就是一次退货加一条差评**，而退货的物流成本往往高于这单的毛利。所以本系统把「实物参数不得凭空编造」写成了跨层的硬约束 —— 缺失的尺寸、材质、承重、组装时间、配送时效会以 `[待确认 xxx]` 显式留白，而不是补一个看起来合理的数字。

**家居出海工作台**把「内容与 Listing 专家 + 数据专家 + 市场研究专家 + 办公助手 + 实时协同」整合进**一个可追踪、可兜底、先确认后执行**的系统。

## 2. 产品目标

| 目标 | 做法 |
| --- | --- |
| 一个入口完成 **对外营销 + 内部办公 + 协同** | 编排器统一调度三类专家与办公工具，侧边栏聚合消息/通讯录/任务/日历/自动化（行业简报 + 选品分析）/产品图 |
| 过程**可见**、结果**可兜底** | 右侧 Agent Trace 实时展示编排步骤；产出物（规格单 PDF / 产品图 / 简报）落库持久化 |
| 写操作 **human-in-the-loop** | 任务 / 日程一律"先出草稿卡 → 用户确认 → 才落库" |
| **实物参数零编造** | 尺寸/材质/承重/组装/配送只能来自输入、附件或引用来源，缺失即显式留白 |
| **企业级** 多人协作 | 组织 + 邀请码、组织内/外部通讯录、实时 IM（人↔人 / 群）、用户级数据隔离与权限 |

## 3. 核心功能

- **多智能体对话**：编排器按需分派 **内容与 Listing / 数据 / 市场研究** 三类专家，综合成带引用的最终回答，必要时产出 PDF。内容专家按渠道 SOP 工作 —— Amazon listing、Wayfair 属性表、独立站商详、Instagram / Pinterest / TikTok、EDM、广告、SEO 选购指南。
- **Agent Trace 追踪 + 预览面板**：右栏两个标签 —— `追踪` 实时显示 intake→planning→delegating→synthesis 每一步；`预览` 以**浏览器式多标签**内联打开产出物、上传件、被引用的网页与知识库文档。
- **办公助手（对话即可发起）**：任务待办、日程日历、资料问答 —— 全部通过聊天用自然语言发起，AI 生成**草稿卡**，用户点确认后才真正写入。涉及美国客户或供应链交期的时间会提醒确认时区。
- **自动化入口（定时跑的分析任务）**：一个入口里两个定时任务 —— ① **行业简报**：配置主题、详略、推送时间与时区，定时抓取并生成**分级来源**摘要（来源分级已纳入 USITC / CBP / CPSC / trade.gov 与家居行业媒体 Furniture Today、Home News Now、HFN、Business of Home）；② **选品分析 BI 仪表盘**：完全基于卖家精灵数据，按「关注全部品类」或「指定品类」+ Amazon 站点 + 每日刷新时间配置，输出关键指标磁贴、带机会分的选品推荐、类目需求趋势折线、品类市场快照表和选品结论；两者都支持「立即刷新」。选品分析**没有兜底路径** —— 拿不到市场数据时直接报错，而不是给一个猜出来的推荐。
- **竞品与市场数据（卖家精灵为主数据源）**：Amazon 竞品与市场数字 —— 价格、BSR、评分、评论数、价格/排名历史、关键词搜索量与流量来源、销量估算 —— 统一走 **卖家精灵（SellerSprite）MCP**。工具面由 `tools/list` 运行时发现，不在代码里手抄厂商接口。公开网络搜索与实时商品页浏览器降级为**兜底**：只在卖家精灵不可用、或所需字段它查不到时启用（Wayfair / 独立站竞品、关税与 CPSC 政策、行业新闻），并在正文里说明该数字是兜底取得的。厂商的**实测值**（价格 / BSR / 评分 / 评论数）与**估算值**（月销量 / 销售额）在提示词层被强制区分，估算值不得当作实测事实。
- **产品与供应商资料 RAG**：上传规格书、打样记录、平台规则、物流与关税文件 → 检索 → 回答附**来源引用**，点击引用可在预览区打开原文（embedding → reranker → 词法多级检索，缺重依赖时自动降级）。支持 PDF、Word、文本与 Excel；Excel 会按工作表和连续数据区域切分，大表分块时重复表头，并单独提取形状/SmartArt 流程图的节点与连接关系。查询理解会做同义扩展（实木↔硬木↔solid wood、头程↔海运）并识别 `product_spec` 意图。
- **产品图 AI 生成**：文生图（Gemini）、上传参考图、一键抠图去背景、按渠道风格（Amazon 合规白底 / Wayfair 列表图 / 独立站 Hero / Instagram / Pinterest）套模板画布合成。模板覆盖家具最需要的图型：**尺寸标注图、材质工艺特写、房间实景、尺度对比**。
- **实时协同**：IM 消息（人↔人 / 群聊、未读数、已读回执、文件消息，基于 SSE 实时推送）+ 通讯录（组织成员 / 外部联系人 / 联系人申请 / 星标 / 我的群组）。
- **账户与个性化**：注册登录、组织与邀请码、可解释且可关闭的**长期业务记忆**（自动学习品类、渠道、目标客户与指标口径偏好，附证据台账；一次性的产品参数不会被记成长期偏好）。

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
│  多智能体核心（src/marketing_agent/，DeepSeek API）              │
│                                                                  │
│   Orchestrator / OA Copilot  ── 任务控制层（不直接干活）         │
│        ├─ delegate → 内容 Agent（Listing / 商详 / 社媒 + PDF）   │
│        ├─ delegate → 数据 Agent（本地 Python 算 ACOS/退货率）    │
│        ├─ delegate → 市场 Agent（卖家精灵 MCP 为主 → 搜索/浏览兜底）  │
│        └─ OA 工具：draft_task / draft_event /                    │
│                    query_* / search_knowledge_base              │
└─────────────────────────────────────────────────────────────────┘
```

- **业务词表（`domain.py`）**：品类、渠道、受众、KPI 和「不得编造」清单集中在一处，所有提示词从这里取词，避免各文件口径漂移。
- **编排器（`orchestrator.py`）**：tool-use 循环（最多 12 轮），并行分派专家、再综合为 markdown。硬约束：**它自己不写文案、不算指标、不声称外部事实、不填实物参数**，一律通过 delegate 工具下派，避免越权与幻觉。
- **OA Copilot（`oa/agent.py`）**：聊天实际运行者，复用编排器的分派/流式机制，额外挂载 OA 工具，一个助手同时覆盖办公流程与营销分派。
- **三类专家（`agents/`）**：内容（11 个渠道 SOP 技能，含 Amazon / Wayfair listing 的字数与合规约束）、数据（自有数据不进 prompt，模型写 pandas 由 `tools/code_exec.py` 在临时目录里执行，算 ACOS/TACOS、转化率、客单价、退货率与扣除退货后的净 ROAS；市场基准对照走卖家精灵）、市场（**先查卖家精灵 MCP**；它覆盖不到的部分才由 `tools/web_search.py` 找到真实商品页，再由 `tools/product_browser.py` 渲染网页、滚动并点击评论入口/加载更多，提取结构化商品信息与可见评论，最后用 `source_scoring` 分级）。
- **数据来源可追溯（`provenance.py`）**：每个带数据的回答末尾都会被**决定性地**追加一段「数据来源」，内容由**实际调用过的工具**生成，而不是让模型自述。专家先渲染自己的来源段，编排器/OA Copilot 再从专家输出里重建合并版，所以模型在汇总时把它删掉也不会丢。

## 5. 典型任务流程示例：
**场景 A · 市场 → 数据 → Listing（一句话完成一条链路）**
用户："帮我看下同价位竞品的 listing 怎么写的，结合上周的广告和退货数据，给这款实木餐桌重写 Amazon 五点描述。"
→ 编排器 `intake/planning` → 并行 `delegating` 市场 Agent（搜索真实竞品页，并用无头浏览器加载动态商品数据与可见评论）+ 数据 Agent（跑上周 ACOS 与退货率）→ `specialist_done` → 内容 Agent 按 `amazon_listing` SOP 产出标题、五点与关键词 → `synthesis` 汇总为带**来源引用**的回答。全过程在右侧 Trace 可见。缺失的尺寸会以 `[待确认 xxx]` 留白。

**场景 B · 对话式办公（请假 / 排会，草稿→确认）**
用户："生成日程"
→ OA 生成**日程草稿卡**（时区感知）→ 用户核对时间点「确认创建」→ 才落库、日历中出现。任务同理，AI 从不擅自"已创建"。
<img width="1280" height="697" alt="image" src="https://github.com/user-attachments/assets/d617f699-e0fa-4554-a6d2-a70707c2069a" />
手动确认后，同步到日程中，并在顶部导航栏提供今日最近日程的预览：
<img width="1278" height="698" alt="image" src="https://github.com/user-attachments/assets/03ca47b3-d336-4953-9a38-c14e75bf425c" />
<img width="1280" height="698" alt="image" src="https://github.com/user-attachments/assets/52cfdcf5-701c-46e0-82e0-b3bce5cc805f" />

**场景 C · 资料问答（规格与制度秒查，来源可溯）**
用户："这款餐桌的板材和承重是多少？"或"公司的报销制度、额度和流程是什么？"→ 检索知识库 → 回答附**来源 capsule** → 点引用在预览区直接打开原始文档。
<img width="1280" height="696" alt="image" src="https://github.com/user-attachments/assets/c109cf91-f21c-4d96-9cec-7ee9bf53ad1b" />

**场景 D · 行业简报日报（自动化 → 行业新闻）**
配置每日摘要主题（如美国家具零售、家具关税）→ 定时抓取 → 生成**分级来源**摘要推送，可手动"立即刷新"。关税与 CPSC 规则变化会被当作重要发现而非背景。
<img width="1280" height="695" alt="image" src="https://github.com/user-attachments/assets/88e46ffb-2791-4837-a753-7297b00e8960" />
可配置自动总结的内容主题、详细程度、自动推送时间：
<img width="1280" height="696" alt="image" src="https://github.com/user-attachments/assets/ca727eac-7a5b-4e68-bf43-7386390a71ec" />
<img width="1280" height="696" alt="24 小时行业新闻自动收集与摘要" src="https://github.com/user-attachments/assets/ae1832b2-a6f0-4512-913e-05ffad7062e9" />

**场景 E · 产品图生成**
上传家具产品图 → 可选是否一键抠图 → 可以选渠道模板（Amazon 合规白底 / 尺寸标注 / 材质特写 / Wayfair 房间实景 / 独立站 Hero / Instagram / Pinterest）/或者直接在下方输入栏输入需求→ 生成 → 历史与再编辑。
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
- **DeepSeek API**（`deepseek-v4-pro` / `-flash` / `-flash-vision-exp`）—— 编排器、专家、OA copilot、视觉
  - `llm_client.py` 把代码里 Anthropic 风格的 Messages 调用翻译成 DeepSeek 的 OpenAI 兼容协议，并处理思考模式与强制 tool_choice 的互斥、图片请求自动路由到视觉模型
  - `httpx` —— 唯一的模型/搜索 HTTP 依赖（连接池复用）
- **卖家精灵 MCP（主数据源）**：`tools/mcp_client.py` 是一个**同步**的极简 MCP 客户端 —— 官方 `mcp` Python SDK 是 asyncio-only，而这套 Agent 栈是同步的（`run_agent` 阻塞循环跑在 `asyncio.to_thread` 的工作线程里），硬接会退化成每次调用重建一个事件循环和 MCP 会话。MCP 在线上不过是 JSON-RPC 2.0 over HTTP POST，所以直接用 `httpx` 说，和 `llm_client` 对 DeepSeek 的做法同源：**在边界翻译，不引入 SDK**。实现了 `initialize`（含 `Mcp-Session-Id` 握手、会话过期自动重握手）、带游标分页的 `tools/list`、`tools/call`，同时兼容 JSON 与 SSE 两种应答体。`tools/sellersprite.py` 在其上做运行时工具发现、命名空间隔离（`sellersprite_*`）、schema 翻译、**按次计费预算上限**与来源包装
- **搜索（兜底）**：`tools/web_search.py` 可插拔 Tavily / Serper / Brave / 博查 / **Gemini**（DeepSeek 无内置联网搜索）。Gemini 走 Google Search grounding，复用图像生成那把 `GEMINI_API_KEY`，不用再注册搜索厂商；配了专用搜索 key 时优先用专用的，因为它们会返回发布日期
- **真实商品页采集**：`playwright` 启动 Chromium，只访问搜索结果中返回的公开商品链接；渲染 JavaScript、滚动页面并点击评论/加载更多控件，读取 JSON-LD、价格、评分、评论总数与当前可见的评论样本。它不会登录、绕过验证码或反爬限制，也不会把少量样本描述成全部用户反馈
- **代码执行**：`tools/code_exec.py` 本地子进程跑模型写的 pandas（DeepSeek 无远程沙箱，见第 8 节安全说明）
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

- **迭代路线**：MVP 营销多智能体 → 引入 OA Copilot（任务/日程/知识库、草稿-确认）→ 企业协同（IM 消息 + 通讯录）→ 体验打磨（引用点开预览、编辑消息重新生成、停止生成、日程时区修正）。
- **智能体运行在 DeepSeek 上**：编排器 `high` 思考强度、专家 `medium`，另用轻量 `deepseek-v4-flash` 做记忆抽取与澄清，带图请求自动路由到 `deepseek-v4-flash-vision-exp`，成本与质量分层。
- 每次改动都在真实浏览器里验证（读取控制台/网络/SSE、点选交互），而非仅跑单测。

## 8. 可信、安全与异常设计

- **草稿 → 确认（human-in-the-loop）**：所有写操作（任务/日程）**永不由模型直接持久化**，先以 `oa_draft` 事件渲染确认卡，用户点确认才命中对应 `POST` 端点；系统提示词禁止模型声称"已提交/已创建"。草稿在前端本地留存，刷新不丢。
- **过程可追踪**：编排/专家生命周期以 SSE 事件（`started` / `orchestrator_step` / `delegating` / `specialist_done` / `assistant_delta` / `artifact_created` / `result`）实时呈现在 Agent Trace。
- **认证与权限**：PBKDF2-SHA256（20 万轮、每用户盐、常量时间比较）、Bearer Token（14 天 TTL）；注册校验中国身份证校验位与邮箱/手机号；对外投影**脱敏**身份证、绝不返回密码哈希。所有受保护路由经 `require_user`，数据读取按 `user_id` 隔离；知识库文档带 `scope`（个人/组织）校验成员，IM 文件下载校验会话成员。
- **优雅降级**：专家不可用时返回 `## …Unavailable` 的 markdown 而非抛错；图像生成永不崩；KB 检索 embedding→reranker→词法逐级降级；**流式失败自动回退** `/complete` 再恢复会话记录，避免结果丢失。
- **时区与时间**：日历存 epoch 瞬时、拒绝过去时间（120s 偏差容忍）、按用户时区调度新闻；OA 提示词注入当前本地时间以正确解析"明天/周五"。
- **反越权 / 反幻觉**：编排器被硬性约束不写文案、不算指标、不编造外部事实，只能下派。
- **代码执行边界**：迁移到 DeepSeek 后没有了远程代码沙箱，分析 Agent 改为在服务端子进程里执行模型写的 pandas（`tools/code_exec.py`）：一次性临时工作目录、只放当次数据文件、120s 墙钟超时、输出截断，进程退出即清理。这不是沙箱——生产部署应把 API 服务本身放进容器（只读根文件系统、禁出网），或用 `MARKETING_AGENT_LOCAL_CODE_EXEC=0` 关闭该能力（分析 Agent 会明确返回不可用）。
- **不编造来源**：主数据源与兜底搜索**都**没配置时，研究 Agent 直接返回「研究不可用」并分别说明两者各自要设置哪个环境变量，而不是凭记忆生成看起来像真的 URL。
- **数据来源分层与可追溯**：卖家精灵为主、搜索/浏览器为兜底；主源不可用时会把这一事实写进给模型的 brief，要求它在 Source Notes 里说明。回答末尾的「数据来源」段由代码按**实际调用过的工具**生成 —— 空结果不算数据源，被厂商拒绝的查询也不算，所以脚注不会谎报来源。
- **计费边界**：卖家精灵按次扣积分，单次请求的调用次数有硬上限（默认 8 次，数据 Agent 4 次，选品分析 16 次），与浏览器 4 页上限同源。选品分析的模型归一化跑在采集**之后**，所以模型侧的 5xx 会重试 3 次，且采集结果按 15 分钟缓存 —— 用户看到「模型过载」后手动重试不会二次扣额度。测试套件用 `tests/conftest.py` 强制清空厂商密钥，避免一次 `pytest` 就把积分刷掉。
- **浏览边界**：商品页浏览器拒绝内网/本机地址和跨站跳转，屏蔽下载及图片/视频等非必要资源，并把网页文字视为不可信证据；研究结论必须给出采集时间、来源链接、实际观察到的价格/评分/评论量和样本数，至少两条不同评论支持后才称为重复痛点。

## 9. 测试与评测

- **后端**：`pytest`，297 个用例覆盖 API、会话/记忆、任务/日历、IM/组织/通讯录、图像、新闻、**自动化选品分析**、KB 检索、来源评分、卖家精灵 MCP 与数据来源标注、OA 工具与 copilot、澄清、记忆抽取、PDF。
  - 代表：`test_routes.py`(41) · `test_sellersprite.py`(32) · `test_selection.py`(33) · `test_image.py`(23) · `test_news.py`(18) · `test_sessions.py`(16) · `test_oa_modules.py`(12) · `test_source_scoring.py`(10) · `test_im.py`(9) · `test_kb_retrieval.py`(6)。
- **前端**：`tsc --noEmit` 类型检查 + 生产 `next build`。
- **运行**：
  ```bash
  pytest tests -q
  ```
  （测试用独立 DB，设置 `MARKETING_AGENT_DB_PATH` 到临时路径、`DEEPSEEK_API_KEY=test-key`、`MARKETING_AGENT_MEMORY_LLM=0`、`MARKETING_AGENT_KB_SEMANTIC=0`、`MARKETING_AGENT_KB_RERANK=0`；**测试全程不出网** —— `tests/conftest.py` 会强制清空 `SELLERSPRITE_SECRET_KEY`，避免 `.env` 里的真密钥让一次 `pytest` 真去调用按次计费的厂商接口。）

## 10. 快速开始

**前置**：Python 3.11+、Node 18+、`DEEPSEEK_API_KEY`（必需）、`SELLERSPRITE_SECRET_KEY`（**竞品与市场数据主数据源**，在 <https://open.sellersprite.com> → 获取密钥 申请）、`GEMINI_API_KEY`（产品图生成 **+** 兜底联网搜索，一把 key 两用）。如果你已有专用搜索服务，也可改用 `TAVILY_API_KEY` / `SERPER_API_KEY` / `BRAVE_SEARCH_API_KEY` / `BOCHA_API_KEY`，它们会优先于 Gemini 生效。

> 不配 `SELLERSPRITE_SECRET_KEY` 服务仍可运行：竞品与市场问题会自动降级到公开搜索 + 实时商品页浏览，回答的「数据来源」段落会标明这是兜底路径。
>
> DeepSeek 没有内置联网搜索：主数据源和五个搜索 key 一个都没配时，研究 Agent 会明确返回「研究不可用」，而不是编造来源。

```bash
# 1) 后端
cp .env.example .env          # 填入 DEEPSEEK_API_KEY / SELLERSPRITE_SECRET_KEY / GEMINI_API_KEY
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
marketing-agent --help         # 内置 CLI（Listing/数据/市场）
```

## 11. 项目结构

```text
src/marketing_agent/          Agent 核心（可安装包 + CLI 入口）
  orchestrator.py             编排循环（营销负责人角色）
  oa/agent.py, oa/tools.py    企业 OA copilot + 草稿/查询工具
  agents/                     content / analytics / research 专家 + base、技能
  tools/                      delegation_tools、image_gen(Gemini)、pdf_tool
    mcp_client.py             同步极简 MCP 客户端（JSON-RPC over HTTP，兼容 SSE 应答）
    sellersprite.py           卖家精灵主数据源：工具发现 / schema 翻译 / 预算上限
    web_search.py             兜底搜索（5 家可插拔）
    product_browser.py        兜底商品页实时采集（Playwright）
  domain.py                   业务词表（品类/渠道/受众/KPI/禁编造清单）
  provenance.py               数据来源台账 + 「数据来源」段落生成
  config.py, source_scoring.py, conversation.py, llm_client.py
server/                       FastAPI 后端
  main.py                     应用工厂、CORS、新闻定时任务
  routes.py                   全部 /api 端点        db.py  SQLite 结构与数据访问
  streaming.py                同步回调 → 异步 SSE 桥  auth.py  密码/令牌/资料校验
  kb_retrieval.py, reranker.py, embeddings.py, query_rewrite.py   KB RAG 管线
  news.py                     行业简报生成      selection.py  选品分析（卖家精灵 → BI 仪表盘）
  memory*.py, clarify.py, im_hub.py, uploads.py, image_*.py
web/                          Next.js 14 前端
  app/page.tsx                单页工作台外壳 + SSE 处理
  components/*.tsx            各功能面板 + chat/preview/auth UI
    automation-panel.tsx      自动化入口（行业新闻 / 选品分析 两个标签）
    selection-panel.tsx       选品分析 BI 仪表盘（磁贴 / 推荐卡 / 趋势折线 / 快照表）
  lib/*                       api、sse、i18n、stores(sessions/im)、oa-drafts
tests/                        pytest 套件（见 §9）
skills/                       业务 SOP 技能（竞品 Listing 对比、新品上架战役）
data/sample_campaign.csv      分析示例输入（含退货列）
render.yaml · vercel.json     部署配置
```

## 12. 当前进度与后续规划

**已完成**
- 营销多智能体编排（内容/分析/研究）+ Agent Trace + 预览多标签
- 企业 OA Copilot：任务 / 日程 / 知识问答（对话发起 + 草稿-确认）
- 企业协同：实时 IM（人↔人/群、已读回执、文件）+ 通讯录（组织/外部/星标/群组）
- 自动化入口：行业新闻自动摘要 + **选品分析 BI 仪表盘**（卖家精灵数据，可设关注品类与每日定时）
- 营销图 AI 生成、可解释营销记忆
- 体验：引用点开预览、编辑历史消息重新生成、停止生成、日程时区修正

**后续规划**
- 选品分析扩展：接入卖家精灵关键词与流量接口做"关键词机会"看板；把选品结论直接一键转成内容 Agent 的 listing 任务
- 知识库组织级共享与权限增强、检索质量评测集
- 传输层可选 WebSocket 替代 SSE（双向、断线更平滑）；多 worker 时用 Redis 做 IM pub/sub
- 移动端适配与更多平台图像模板

## 13. 项目复盘

- **收获**：跑通了"编排器 + 多专家"的多智能体协作、SSE 流式与 Agent Trace、human-in-the-loop 的草稿-确认范式、RAG 检索与来源分级，以及一套"AI Coding + 浏览器实测"的开发闭环。
- **关键权衡**：
  - **SSE vs WebSocket**：本项目是"服务器→客户端"单向推送（追踪/增量/草稿），SSE 更轻、自动重连、走标准 HTTP，故选 SSE；IM 也复用同一套。真正需要双向低延迟（如输入中状态）时可升级 WebSocket。
  - **单进程 pub/sub**：`im_hub` 用进程内内存 hub，简单够用；水平扩展需换 Redis。
  - **本地 embedding 可选**：`sentence-transformers` 依赖重，设为可选并对检索做多级降级，保证无 GPU 环境也能跑。
- **不足与改进**：选品分析目前每次固定跑一组接口，尚未按品类自适应选择接口；KB 组织级共享待增强；完善系统功能，如后续获得许可和企业数据后，加入AI化的BI与客户成功功能。

---

> 部署：后端 Render（`render.yaml`，使用 Playwright Docker 镜像，并以持久磁盘挂 SQLite / rembg 权重；容器启动时修正挂载盘权限后降权运行）；前端 Vercel（`vercel.json`，构建 `web/`）。
