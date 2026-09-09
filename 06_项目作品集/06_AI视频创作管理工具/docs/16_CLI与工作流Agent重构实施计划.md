# CLI 与工作流 Agent 重构实施计划

**状态**：已完成  
**日期**：2026-07-19  
**目标**：全部正式业务保留可复现 CLI；HTTP API、CLI、工作流 Agent 共享同一命令层；在应用最右侧增加项目级 Agent 聊天栏。

## 1. 不可破坏的约束

1. CLI 与 Agent 统一调用 `CommandBus`；页面 HTTP 路由与命令 handler 必须复用同一 Application Service / Repository，禁止复制业务算法。
2. Agent 只能调用命令注册中心中的结构化白名单工具，禁止任意 Shell、`shell=True` 和直接改库。
3. 所有项目命令显式携带 `project_id`，不得用隐式当前目录跨项目操作。
4. 章节、自定义正则、手动切分保持确定性；只有按时长切分调用 LLM。
5. 剧本转换、实体分析、提示词生成等 LLM 行为继续使用提示词管理和独立使用点配置，不增加内嵌业务提示词。
6. `video_agent` 保留视频请求整理用途；新建 `workflow_agent` 处理项目聊天和命令编排。
7. 删除、覆盖、批量 LLM、图片和视频生成必须经后端审批策略确认，不能仅靠前端弹窗。
8. 命令结果统一返回 `ok`、`command`、`operation_id`、`project_id`、`revision`、`data`、`warnings`。

## 2. 目标结构

```text
UI action -> HTTP Route ───────────────┐
CLI / Agent Tool -> CommandBus ───────┼-> Application Service -> Repository / Provider
```

新增后端模块：

```text
src/ai_video_manager/commands/
  bus.py          命令分发、上下文、结果、错误
  registry.py     命令定义、参数模型、权限与确认元数据
  handlers.py     项目、预处理、提示词、视频和配置等通用命令
  asset_production.py  实体档案、视觉风格与资产生成命令

src/ai_video_manager/agent/
  graph.py        LangGraph ReAct 循环和审批中断
  service.py      会话、消息、运行和事件服务
  repository.py   SQLite 持久化
```

新增前端模块：

```text
frontend/src/api/agent.js
frontend/src/hooks/useWorkflowAgent.js
frontend/src/hooks/useAgentInvalidation.js
frontend/src/hooks/useStickyBottom.js
frontend/src/components/AgentDock.jsx
frontend/src/components/AppNavigation.jsx
frontend/src/domain/agent/commandEffects.js
```

## 3. 命令覆盖

CLI 保持入口 `ai-video-manager`，采用领域子命令并支持 `--json`：

- `project list|show|create|update|delete|export|import`
- `document import|show`
- `preprocess split`
- `segment list|show|create|update|reorder|delete`
- `script show|save|convert|convert-all`
- `asset list|import|rename|delete`
- `entity list|show|create|update|delete|extract|asset-add|asset-remove`
- `prompt-template list|show|create|update|delete|versions|restore`
- `prompt-card list|show|generate|update|delete|lock|unlock|rerun|match-subjects`
- `video task-list|task-status|request|retry|download|delete`
- `config show|provider-test|model-list|use-case-set`
- `workflow status`

旧 `ingest` 只保留兼容入口，改为调用正式导入与确定性切分命令，不再执行离线剧本转换。

## 4. Agent 运行流程

```text
用户消息
  -> 读取当前项目和页面上下文
  -> workflow_agent 生成一个下一步结构化工具动作
  -> CommandBus 校验命令、项目、权限、revision
  -> 只读工具立即执行并把结果作为 observation 回传 LLM
  -> 高风险工具暂停并等待确认，确认后继续循环
  -> Agent 判断任务完成或继续下一步
  -> 同步返回本轮结果；前端先乐观插入用户消息，再显示运行状态
```

只读命令自动执行；一般写入显示操作卡；删除、覆盖、外部计费和批量任务必须确认。确认信息包含命令、项目、对象数量、模型和可能的外部消耗。

## 5. 会话和审计

新增表：

- `agent_threads`：项目级会话。
- `agent_messages`：用户、助手和工具消息。
- `agent_runs`：运行状态、当前节点、审批状态。
- `agent_tool_calls`：命令、参数、确认、结果和错误。
- `command_operations`：所有 CLI/API/Agent 命令的统一操作审计。

刷新后恢复当前项目的 Agent 会话；不同项目严格隔离。API Key、完整认证头和敏感路径不得写入消息或工具结果。

## 6. 前端交互

- Agent Dock 位于应用最右侧，不嵌入具体业务卡片。
- 桌面默认宽 360px，可在 320-520px 调整，可折叠为 44px 图标栏。
- 窄屏使用右侧抽屉，不挤压业务表单到不可操作。
- 上下文包含当前项目、页面、选集、实体和提示词卡 ID；正文按需由只读命令获取。
- 工具调用显示结构化操作卡，确认、取消、重试和停止都能实际工作。
- 工具卡显示命令、参数、执行状态和可展开的工具返回结果。
- 会话保留最近 8 条消息，较早内容自动压缩为持久摘要；摘要记录压缩位置，避免重复拼接。
- Agent Dock 支持创建会话分支、自动切换新分支和返回历史分支；分支继承摘要与分支点后的近期消息。
- 命令完成后按返回的变更域刷新对应前端数据，不直接篡改 React 本地业务状态。
- 所有写命令必须声明 `effects`；Agent、CLI 和命令 HTTP 结果携带同一失效数据域。

## 7. 实施顺序

1. 建立命令模型、注册中心、CommandBus 和统一结果。
2. 重构 CLI 并覆盖现有主要业务，移除旧离线转换。
3. 增加命令审计与 CLI/API 一致性测试。
4. 增加 `workflow_agent` 配置与提示词类别。
5. 实现 LangGraph 会话、审批中断、命令工具和 SSE。
6. 实现全局右侧 Agent Dock 和持久化布局。
7. 迁移关键 HTTP 路由到 CommandBus，避免新旧逻辑分叉。
8. 按 `docs/03_TDD测试驱动开发规范.md` 完成单元、契约、集成和浏览器测试。

## 8. 完成标准

1. 同一业务通过 UI、CLI、Agent 执行时，调用同一 handler 并产生一致数据和审计记录。
2. CLI 能独立完成“创建项目 -> 导入 -> 切分 -> 保存剧本 -> 实体管理 -> 提示词卡 -> 视频任务”的主要流程。
3. Agent 可完成只读查询、一般修改和需确认操作；拒绝任意 Shell 和跨项目参数。
4. Agent 刷新后会话和待确认操作可恢复。
5. 桌面、窄屏无横向溢出；Agent 收起后不影响现有三列视频工作区。
6. 后端全量测试、前端 Vitest、Playwright 和生产构建通过，服务冷重启后 `/api/health` 正常。

## 9. 本次落地结果

- 已建立 `CommandBus`、命令注册中心、统一结果和 `command_operations` 审计记录。
- CLI 已保留 `ai-video-manager` 入口，覆盖项目、文档、预处理、分集、剧本、素材、实体、提示词模板、提示词卡、视频任务、配置和工作流状态主要操作；支持 `--json` 和高风险操作 `--yes`。
- 旧 `ingest` 仅兼容导入与切分，不再执行旧的离线剧本转换。
- 已新增 `workflow_agent` 使用点、示例模板、会话/运行/工具调用/事件持久化及审批接口。
- 已新增最右侧 Agent Dock，支持项目级会话、命令预览、审批、取消、折叠、调宽和刷新恢复。
- 已将 Agent 执行改为 LangGraph ReAct 循环：每轮只调用一个命令，读取结果后再决定下一步，最多 12 步并支持确认后续跑。
- 已增加 `project.settings.update`、`file.list`、`file.read`、`file.write` 工具；文件工具只允许当前项目数据目录内的相对路径，文本写入上限 2MB。
- 已增加 `entity-profile.list/show/update`，Agent 项目上下文直接携带 V3 实体档案、已有设定、最新资产提示词、活动视觉风格、生成预设和图片任务摘要。
- 已将实体档案、视觉风格和资产生成命令拆到 `commands/asset_production.py`，不再继续扩张通用 handler。
- 已建立命令 `effects` 契约和前端统一失效刷新；Agent 写入后资源、实体、素材、提示词和视频按域同步。
- 已统一浏览器 UI 状态读写入口，并为项目加载、视频轮询和 Agent 响应增加跨项目竞态保护。
- 已约束实体资产链路优先复用现有档案，只有档案为空或用户明确要求重新分析时才调用 `entity.extract`。
- 已修复实体提取命令将 `segment_ids` 错传给服务的问题，统一映射为 `episode_ids`。
- 已增加自动上下文压缩与持久化会话分支，避免长会话无限膨胀并支持从当前工作状态探索不同方案。
- 已支持“先读取剧本，再生成并保存项目提示词”的多步任务，前端工具卡可展开查看返回结果。
- 已验证真实只读 Agent 请求能返回春潮项目名称；未执行真实写入、图片或视频生成，避免测试产生外部消耗。
- 全量后端测试、前端构建、Vitest、桌面/窄屏运行态和 CLI 只读验收通过；SSH 保持关闭，Docker 未启动。
