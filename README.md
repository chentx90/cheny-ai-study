# AI 应用学习与实践

> 从 Python 补强 → Prompt 工程 → Agent → RAG → 工程化部署的学习轨迹，以及 5 个可演示的 AI 应用项目。

2026 年 5 月起，我用约 3 个月时间，从「看得懂 Python 语法」转向 AI 应用方向（Prompt / Agent / RAG / 工作流）。
这个仓库同时承担两件事：

- **学习记录** —— 路线图、周计划、每个阶段的笔记与作业验收
- **作品集** —— 5 个项目，从单文件 CLI 工具一路做到前后端 + 容器化部署 + 权限体系

---

## 作品集一览

| 项目 | 一句话 | 技术栈 | 状态 |
| --- | --- | --- | --- |
| [`06_AI视频创作管理工具`](06_AI视频创作管理工具/) | 本地优先的 AI 视频创作工程管理平台 | FastAPI · SQLite · LangGraph · React 18 + Vite · Docker | 已完成 V2 重构 |
| [`04_AI漫剧管理器重启`](04_AI漫剧管理器重启/) | 小说 → 设定库 → 分集/分镜 → 视频提示词的受控 Agent 管线 | Python · Typer/Rich · LangChain · LangGraph · JSON 状态机 | 端到端可跑通 |
| [`03_AI漫剧管理器`](03_AI漫剧管理器/) | 上一版原型：小说 → 剧本 → 分镜 → 实体提取 → 提示词 | Python · LangChain · LangGraph · Typer · Git 版本化 | Demo 完成 |
| [`02_rag_知识问答`](02_rag_知识问答/) | RAG 检索策略对比实验：切块 × 模型 × 文本形态 | sentence-transformers(BGE) · Chroma · LangChain · pypdfium2 | 6 组实验 + 评测 |
| [`05_检索增强生成`](01_py练习_日报摘要器/05_检索增强生成/) | 模块化解耦的 RAG 系统框架（网关 / 检索 / 存储适配器） | FastAPI · PostgreSQL + pgvector · MinIO · Next.js 14 · Docker Compose | 设计 + 骨架 |
| [`01_py练习_日报摘要器`](01_py练习_日报摘要器/) | 日报文字 → 结构化 JSON 的 CLI 工具，附带完整学习轨迹 | Python · requests · OpenAI 兼容协议 | V1 完成 |

---

## 项目详情

### 06_AI视频创作管理工具 · 最完整的一个

本地优先的 AI 视频创作**工程管理平台**。定位不是演示页，而是固定后台应用壳：所有业务围绕「已选择的项目」展开，每个项目的数据写入独立目录，避免项目间数据混用。

**核心模块**

- **项目管理** —— 初始化 / 切换项目，维护分类与简介
- **预处理** —— 录入原始文本，按章节 / 手动标记 / 长度切分，生成脚本
- **资源管理** —— 跨集实体清单、实体卡库、原生资产生成、项目素材
- **视频生成** —— 三栏工作台（剧本 / 提示词卡片 / 视频任务与候选结果），支持卡片锁定、重跑、实体匹配、结果追回与采用
- **提示词管理** —— 模板库版本化，可复制、增删改查、回滚为新版本
- **账户与权限** —— 局域网多人登录，项目级 ACL（viewer / editor / owner），管理员后台，分集编辑锁（30 分钟租约 + 续期）
- **图片资产生产** —— 接入 OpenAI 兼容图片网关，按人物 / 场景 / 物品分别配置服务商、模型、尺寸、比例、生成数量

**工程规模**：后端 83 个 Python 模块，前端 84 个源文件，19 篇设计文档（项目结构、技术架构、TDD 规范、领域与 API 契约、部署审计等）。
**质量记录**（见 `docs/14_V2完成审计与部署记录.md`）：pytest 63 项、Vitest 4 项、Playwright 端到端、功能冒烟 19 项、API 验收 7 项、Docker Compose 校验与 NAS 容器健康检查全部通过。

**技术栈**：FastAPI · uvicorn · pydantic v2 · langchain-openai · langgraph · SQLite · Pillow · python-docx；前端 React 18 + Vite 6 + Vitest；Docker / Docker Compose；Playwright E2E。

### 04_AI漫剧管理器重启 · 受控 Agent 管线

小说原文 → 设定库 → 分集/场景 → 剧本/分镜 → 视频提示词的端到端管线。

设计上的关键取舍：**每个阶段 LLM 只做 schema → schema 的约束变换，状态全部住在结构化 JSON 里**，因此随时可以手动介入、断点续跑、人工检查。管线共 8 个阶段，其中 2 个人工检查点：

```
原文导入 → S1 切集/场景 → [检查点①] → S2 实体设定库 → [检查点②]
        → S3 滚动摘要 → S4 分镜剧本（反思环≤2轮） → S5 角色绑定 → S6 视频提示词
```

**技术栈**：Python 3.11+ · FastAPI · Typer + Rich · pydantic v2 · LangChain · LangGraph · json-repair · Docker。

### 03_AI漫剧管理器 · 原型版

CLI 工具，跑通「小说 → 剧本 → 分镜 → 人物/场景/道具提取 → 提示词生成」的核心链路。用 Git 管理版本（每次操作自动 commit），LangGraph 编排多步 AI 流程，JSON 文件存储所有数据。36 个源码模块，附 `项目设计说明书.md` 与 `CLI指令手册.md`。

**技术栈**：Python 3.14 · LangChain · LangGraph · Typer + Rich · JSON 文件存储 · Git（subprocess）。

### 02_rag_知识问答 · RAG 检索策略对比实验

面向 4–5 万份归档文档构建的本地 RAG 问答系统，重点在**控制变量实验**：同样的问题集，比较不同数据处理、分块策略与 embedding 模型的检索效果。

| 组 | 模型 | 数据类型 | 切块方式 |
| --- | --- | --- | --- |
| A1 | BGE-M3 (568M) | 结构文本 | 标题分割 |
| A2 | BGE-M3 (568M) | 混合文本 | 递归分割 |
| A3 | BGE-M3 (568M) | 提取文本 | 长度 1024 |
| B1 | BGE-M3 (568M) | 提取文本 | 长度 2048 |
| C1 | BGE-Large-zh-v1.5 (326M) | 结构文本 | 标题分割 |
| D1 | BGE-VL-Large (428M) | PDF 文件 | 按页分割 |

**评测指标**：Hit Rate@5（top-5 至少命中一个金标）、MRR@5（金标平均倒数排名）。
仓库内含 500 篇清洗后的样本文本（原始 / 提取 / 混合 / 结构 / PDF 五种形态各 100 篇）与评测集。

**技术栈**：Python 3.11 · sentence-transformers · chromadb · langchain(text_splitter) · pypdfium2。
**数据边界**：embedding 与检索全部本地完成，数据目录不入 Git。

### 05_检索增强生成 · 模块化 RAG 框架

围绕**解耦**设计的 RAG 系统框架，每个模块可独立容器化、通过稳定 API 通信：

```
Frontend → Backend / RAG Gateway → 检索策略 → 存储适配器 → 数据库 / 索引 / 对象存储
```

模块划分为 `frontend`、`backend`、`ingestion`、`database`、`evaluation`，配套 12 篇设计文档（总体架构、数据接入与清洗入库、存储与索引适配器、召回策略、编排网关与 Agent 路由、容器化部署与模块边界等）。

**技术栈**：FastAPI · asyncpg · PostgreSQL + pgvector · MinIO · python-docx / python-pptx / pandas · Next.js 14 + TypeScript + Tailwind · Docker Compose。
**当前状态**：设计文档、模块骨架、ingestion 管道与评估框架已落地；OCR 与部分文档格式解析在文档中明确标注为待实现——这是有意保留的「设计先行」阶段产物。

### 01_py练习_日报摘要器 · 起点项目 + 学习轨迹

把一段工作日报文字提取成结构化 JSON 的 CLI 工具：输出「完成项 / 进行中 / 计划项 / 风险点」四类，自动保存调用历史。

**技术栈**：Python 3.11+ · requests · python-dotenv · argparse · OpenAI 兼容协议（经 NewAPI 聚合层）。

这个目录同时是整个学习过程的存档：

| 目录 | 内容 |
| --- | --- |
| `00_总览/路线图.md` | 6 个月阶段规划：Python 补强 → LLM API/Agent → RAG 全链路 → 工作流编排 → 部署 |
| `01_Python补强/` | Python 工程化练习（日志、异常、文件 IO、HTTP 调用等） |
| `02_Prompt工程/` | Prompt 对比实验（同一任务多版本提示词 + 结果对比） |
| `03_Agent与工作流/` | 工具调用 / 多工具协作 Demo |
| `04_RAG与记忆系统/` | 《生产级 RAG Pipeline 搭建指南》等笔记 |
| `周计划/` · `作业与验收/` | 每周目标与逐项验收清单 |

---

## 能力覆盖

| 方向 | 具体做过的事 |
| --- | --- |
| **LLM 调用** | OpenAI 兼容协议封装、流式输出、function call / tool use、JSON 模式、超时与重试、多模型切换（经 NewAPI 聚合） |
| **Prompt 工程** | 结构化输出约束、Few-shot、CoT、角色设定、模板集中管理与版本化、输出对比评测 |
| **Agent** | LangGraph 状态机编排、工具注册与调用、人工检查点、断点续跑、schema 约束变换、反思环 |
| **RAG** | 文档切分策略、清洗与元数据、embedding 模型选型、Chroma / pgvector 向量库、召回评测（Hit Rate@5 / MRR@5）、OCR 与多格式接入 |
| **工程化** | FastAPI + pydantic v2、SQLite / PostgreSQL、MinIO 对象存储、Docker Compose 多容器编排、React 18 + Vite、Next.js 14、pytest / Vitest / Playwright、项目级 ACL 与多人协作 |

---

## 目录结构

```text
.
├── 01_py练习_日报摘要器/      # 日报摘要器 CLI + 学习轨迹（笔记/周计划/作业）
│   ├── 00_总览/  01_Python补强/  02_Prompt工程/  03_Agent与工作流/
│   ├── 04_RAG与记忆系统/  周计划/  作业与验收/
│   └── 05_检索增强生成/       # 模块化 RAG 框架（设计 + 骨架）
├── 02_rag_知识问答/           # RAG 检索策略对比实验 + 样本数据集
├── 03_AI漫剧管理器/           # 漫剧管理器原型（CLI + LangGraph）
├── 04_AI漫剧管理器重启/       # 漫剧管理器重启版（受控 Agent 管线）
└── 06_AI视频创作管理工具/     # AI 视频创作工程管理平台（前后端 + 容器化）
```

每个项目都是独立的工程，进入对应目录看各自的 `README.md` 获取安装与运行方式。

---

## 配置与数据说明

- **密钥一律走环境变量**：仓库内只保留 `.env.example` 与 `config.example.toml`，真实 Key 不落库。使用前把示例复制为 `.env` / `config.toml` 并填入自己的值。
- **不入库的内容**：大体积媒体素材（视频 / 图片 / PDF）、运行时数据与生成物、上传缓存、向量库持久化文件、第三方业务文档。相关规则见 `.gitignore`。
- **个人路径已脱敏**：文档与代码中的本机绝对路径均替换为 `<REPO_ROOT>` / `<MODELS_DIR>` 等占位符，按自己环境调整即可。

---

## 说明

本仓库为个人学习与作品展示用途。项目均为学习过程中的实践产物，其中 `05_检索增强生成` 处于设计先行阶段，`03_AI漫剧管理器` 已被 `04_AI漫剧管理器重启` 取代——保留它们是为了完整呈现技术方案的演进过程。
