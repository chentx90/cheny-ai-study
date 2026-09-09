# V2 领域与 API 契约

> 状态：V2 正式契约（2026-07-18 切换）
> 日期：2026-07-18  
> 上位文档：`docs/12_V2大重构实施计划.md`

## 1. 唯一领域语言

| 名称 | 定义 | 禁止混用 |
|---|---|---|
| Project | 所有生产数据和文件的隔离边界 | 不允许跨项目文件引用 |
| Document | 用户导入的原始文件和解析文本 | 不表示分集 |
| Episode | 一集内容，拥有原文和剧本 | 不再拆出 Script 聚合 |
| PromptCard | 可独立生成视频的分镜生产单元 | 不再建立 Shot 聚合 |
| EntityCard | 人物、场景或物品在特定状态下的实体 | 素材不是实体副本 |
| ProjectAsset | 项目内唯一文件记录 | 实体卡只建立引用 |
| AIRun | 一次可追踪的 LLM 调用 | 不保存 thinking |
| VideoTask | 一次不可变的视频请求快照 | 状态不是前端临时值 |
| VideoOutput | 视频任务产生的一个本地候选结果 | 与任务分离 |

## 2. 聚合关系

```text
Project 1--N Document
Project 1--N Episode
Episode 1--N PromptCard
PromptCard N--N EntityCard (PromptCardEntityLink)
EntityCard N--N ProjectAsset (EntityMaterialLink)
PromptCard 1--N VideoTask
VideoTask 1--N VideoOutput
Project 1--N AIRun
```

PromptCard 的 `episode_id` 在迁移期与旧 `segment_id` 使用相同 ID。V2 正式接口只使用 episode 术语，兼容接口在最终切换前保留只读能力。

## 3. 状态定义

### Episode

```text
source_ready -> script_ready
script_ready -> source_ready  # 用户清空剧本时
```

### AIRun

```text
queued -> running -> succeeded
                  -> failed
```

### VideoTask

```text
queued -> preparing -> submitted -> processing -> succeeded
         |            |            |            -> failed
         |            |            -> cancelled
         -> failed    -> failed
```

任务状态由后端持久化，前端只能发起命令和显示状态。

## 4. V2 REST 资源

```text
GET    /api/v2/projects/{project_id}/episodes
POST   /api/v2/projects/{project_id}/episodes
PUT    /api/v2/projects/{project_id}/episodes/reorder
PATCH  /api/v2/projects/{project_id}/episodes/{episode_id}
DELETE /api/v2/projects/{project_id}/episodes/{episode_id}

GET    /api/v2/projects/{project_id}/episodes/{episode_id}/prompt-cards
POST   /api/v2/projects/{project_id}/episodes/{episode_id}/prompt-cards/generate
POST   /api/v2/projects/{project_id}/prompt-cards/{card_id}/rerun
PATCH  /api/v2/projects/{project_id}/prompt-cards/{card_id}
DELETE /api/v2/projects/{project_id}/prompt-cards/{card_id}

POST   /api/v2/projects/{project_id}/episodes/{episode_id}/entity-matches/run
PUT    /api/v2/projects/{project_id}/prompt-cards/{card_id}/entity-links

POST   /api/v2/projects/{project_id}/prompt-cards/{card_id}/video-tasks
GET    /api/v2/projects/{project_id}/video-tasks
POST   /api/v2/projects/{project_id}/video-tasks/{task_id}/retry
POST   /api/v2/projects/{project_id}/video-outputs/{output_id}/adopt
GET    /api/v2/projects/{project_id}/video-outputs

GET    /api/v2/projects/{project_id}/ai-runs
GET    /api/v2/projects/{project_id}/ai-runs/{run_id}
```

## 5. 并发与错误契约

- 可编辑聚合返回 `revision`。
- 修改请求携带当前 `revision`，不一致返回 HTTP 409。
- 删除被引用资源返回 HTTP 409，并列出引用类型和数量。
- 外部服务未配置返回 HTTP 422，不应在页面加载或普通保存时触发。
- 外部超时返回稳定错误码，保留 AIRun/VideoTask 记录供重试。
- API 错误响应统一为 `{code, message, details, request_id}`。

## 6. 迁移约束

- V2 schema 通过版本 2-5 增量迁移；版本 5 删除 Shot 与 workspace blob。
- `project_segments + project_scripts` 合并写入 `episodes`。
- PromptCard 直接关联同 ID Episode，不从 Shot 重建业务内容。
- 迁移器可重复执行，重复执行不得增加记录。
- 校验至少覆盖记录数量、悬空 PromptCard 和悬空 VideoTask。
- 正式写链已切换，禁止旧表与新表双写；组合读取使用 `GET /api/projects/{id}/session`。

迁移命令：

```bash
python scripts/migrate_v2.py database/app.db --dry-run
python scripts/migrate_v2.py database/app.db
python scripts/migrate_v2.py database/app.db --restore database/app.v1-backup-<timestamp>.db
```

正式迁移会先使用 SQLite backup API 创建一致性备份。恢复操作必须在应用服务停止后执行。
