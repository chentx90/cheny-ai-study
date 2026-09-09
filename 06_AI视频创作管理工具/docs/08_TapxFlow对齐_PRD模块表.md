# TapxFlow 对齐 PRD：可落地模块表

**目标**：把 TapxFlow 画布能力压成当前仓库可实施的模块、优先级与接口草案。  
**原则**：本地优先、复用现有 Project / Segment / EntityCard / PromptCard / VideoTask；先补「分镜工业化 + 资产引用」，再上「节点画布」。  
**关联**：现有 API 见 `src/ai_video_manager/api/`；视频页见 `frontend/src/views/VideoView.jsx`。

---

## 1. 优先级定义

| 级 | 含义 | 验收标准 |
|----|------|----------|
| **P0** | 2–3 周可交付，直接提升成片可控性 | 不改导航也能在「视频生成」页完成：拆镜 → @资产 → 首帧/视频条件 → 任务回流 |
| **P1** | 画布 MVP + 设定库 | 有独立画布页；分镜 ↔ 画布往返；Series bible 生效 |
| **P2** | 工业化与生态 | 批量管线、Agent、工作流库、分享广场 |

---

## 2. 模块总表

| ID | 模块 | 优先级 | 对标 TapxFlow | 现状 | 前端落点 | 后端落点 |
|----|------|--------|---------------|------|----------|----------|
| M1 | 镜头模型（Shot）升级 | P0 | Storyboard shot list | `Shot` 表已有，UI 弱 | Video 中栏改镜头列表 | 扩展 prompt-cards / shots API |
| M2 | 分镜监视器 | P0 | Preview monitor | 已并入视频生成页右栏 | Video 右栏监视器+任务 | 任务 `result_path` + 资产 URL |
| M3 | `@` 资产引用 | P0 | @ asset mention | 有主体匹配，无 `@` 语法 | Prompt 输入 `@` 补全 | 解析 `@card_xxx` → assets |
| M4 | 视频参考模式 | P0 | F/L · Multi · Omni | 仅 model/ratio/duration | VideoRequestDialog 增 mode | `GenerateVideoRequest` 扩展 |
| M5 | 摄影机/风格写入 Prompt | P0 | Camera Control / Style | 无 | 生成前可选预设 | 可选：模板变量 `$camera` |
| M6 | 画布往返（轻量） | P1 | Canvas round-trip | 无 | 「送到画布 / 收回分镜」 | canvas graph + 回流 API |
| M7 | 节点画布 MVP | P1 | Infinite canvas | 无 | 新路由 `canvas` | `canvas_graphs` 表 |
| M8 | Series bible | P1 | Series bible | 无 | 项目设定页 | `project_bible` |
| M9 | 提取冲突复核 | P1 | Conflict review | 智能绑定有，无冲突仲裁 | Resource 冲突抽屉 | extract diff API |
| M10 | 批量管线 + 闸门 | P2 | Batch / AI Director | workflow 状态机有 | 批量面板 | pipeline job |
| M11 | Agent 对话制片 | P2 | Agent | `video_agent` 模板有 | Agent 面板 | agent run API |
| M12 | 工作流库 / 分享 | P2 | Workflow library / Share | 无 | 模板市场 | workflow pack |

---

## 3. P0 详细（先做）

### M1 — 镜头 = PromptCard 工业化

**产品**：一集剧本 → AI 拆成有序镜头；每镜可改提示词、锁卡、出首帧/视频。  
**映射**：继续用 `PromptCard` 作为 Shot 视图模型（已有 order / source_text / duration / locked）。

| 项 | 内容 |
|----|------|
| UI | 左：集列表；中：镜头列表+编辑（右下角自定义拖高，`resize: none`）；右：任务/预览（现 Video 三栏强化） |
| 验收 | 生成卡片后可逐镜编辑并提交视频；锁定卡不可重跑 |

**接口（已有为主）**

```
GET  /api/projects/{id}/segments/{seg}/prompt-cards
POST /api/projects/{id}/segments/{seg}/prompt-cards/generate
PUT  /api/prompt-cards/{id}
POST /api/prompt-cards/{id}/rerun
POST /api/prompt-cards/{id}/video-tasks
```

**增量**：`SavePromptCardRequest` 增加可选 `camera` / `style_preset` / `first_frame_asset` / `last_frame_asset`。

---

### M2 — 监视器

| 项 | 内容 |
|----|------|
| UI | 选中镜头显示：关联 VideoTask 最新完成态、本地 `result_path` 预览、Mock 文本占位提示 |
| 验收 | 完成任务可在页内播放/打开；Mock 模式明确标注 |

**接口**：复用 `GET /api/videos/tasks?project_id=&segment_id=`；静态文件已有 assets 路由，generated 需补：

```
GET /api/projects/{id}/generated/{path}
```

---

### M3 — `@` 资产引用

| 项 | 内容 |
|----|------|
| 语法 | 提示词内 `@角色名` 或 `@card_xxxxxxxxxxxx` |
| 行为 | 输入 `@` 弹出实体卡；保存时写入 `anchor_text`；生成视频时自动 `collect_video_assets` |
| 验收 | 不选手动 assets，仅靠 `@` 也能把参考图带进任务 |

**接口增量**

```
POST /api/prompt-cards/{id}/resolve-mentions
Body: { "prompt_text": "..." }
Resp: { "entity_card_ids": [], "anchor_text": "...", "missing": [] }
```

生成路径：`video-tasks` 内先 `resolve-mentions` 再 `collect_video_assets`（可服务端隐式完成）。

---

### M4 — 参考模式

`GenerateVideoRequest` / `GeneratePromptCardVideoRequest` 扩展：

```json
{
  "reference_mode": "none | first_last | multi | omni",
  "first_frame": "assets/...",
  "last_frame": "assets/...",
  "reference_images": ["assets/..."],
  "reference_videos": [],
  "reference_audios": []
}
```

| mode | 规则 |
|------|------|
| first_last | 1–2 张图 |
| multi | 多图，无音视频 |
| omni | 允许图/视频/音频；无 Omni 能力的 adapter 返回 400 |

前端：`VideoRequestDialog` 增加 mode 与帧选择；设置页展示当前 video provider 是否支持各 mode（预检扩展）。

---

### M5 — 摄影机 / 风格预设

| 项 | 内容 |
|----|------|
| 数据 | 本地 JSON 预设（机位/镜头/焦距/光圈 + 风格标签） |
| 行为 | 选中后拼进 prompt 后缀或 `$camera` 模板变量 |
| 验收 | 同一镜切换预设，重跑后 prompt 可见差异 |

**接口（可选）**

```
GET /api/style-presets
GET /api/camera-presets
```

P0 可先前端静态常量，不强制后端。

---

## 4. P1 详细

### M7 — 节点画布 MVP（最小闭环）

**只做 6 类节点**：`text` · `image` · `video` · `entity_ref` · `prompt_card` · `group`  
**不做**：3D 导演台、全景、九宫格魔法按钮（放 P2）。

| 存储 | `canvas_graphs(project_id, id, name, graph_json, updated_at)` |
|------|------|
| graph_json | `{ nodes: [{id,type,x,y,data}], edges: [{id,source,target,dataType}] }` |
| dataType | `text \| image \| video \| audio \| any` |

**接口草案**

```
GET    /api/projects/{id}/canvases
POST   /api/projects/{id}/canvases
GET    /api/canvases/{canvas_id}
PUT    /api/canvases/{canvas_id}          # 保存 graph
POST   /api/canvases/{canvas_id}/run-node # 执行单节点生成
DELETE /api/canvases/{canvas_id}
```

**run-node Body**

```json
{
  "node_id": "n1",
  "prompt": "...",
  "model": "...",
  "reference_mode": "first_last",
  "inputs_from_edges": true
}
```

前端：`@xyflow/react`；导航增加「画布」。

---

### M6 — 画布往返

```
POST /api/projects/{id}/segments/{seg}/export-to-canvas
Resp: { "canvas_id": "...", "node_ids": ["..."] }

POST /api/canvases/{canvas_id}/import-to-storyboard
Body: { "segment_id": "...", "node_ids": ["..."] }
Resp: { "prompt_cards": [...], "video_tasks": [...] }
```

验收：分镜台一键导出 → 画布并行出片 → 一键收回更新卡片/任务。

---

### M8 — Series bible

```
GET/PUT /api/projects/{id}/bible
{
  "worldview": "...",
  "relationships": "...",
  "platform_rules": "...",
  "extra": {}
}
```

生成大纲/剧本/提取/prompt-cards 时，服务端自动把 bible 拼进 system 或模板上下文（新变量 `$bible`）。

---

### M9 — 冲突复核

```
POST /api/projects/{id}/entities/extract-preview
Resp: {
  "candidates": [...],
  "conflicts": [
    { "entity_name": "小明", "field": "state", "old": "幼年", "new": "青年", "card_id": "..." }
  ]
}

POST /api/projects/{id}/entities/resolve-conflicts
Body: { "resolutions": [{ "conflict_id": "...", "action": "keep|adopt|custom", "value": "..." }] }
```

---

## 5. P2 详细（后置）

| 模块 | 接口草案 | 说明 |
|------|----------|------|
| M10 批量管线 | `POST /api/projects/{id}/pipelines` · `GET .../pipelines/{job_id}` | stages: script→storyboard→image→video→compose；`review_gate` + `budget_credits` |
| M11 Agent | `POST /api/projects/{id}/agent/runs` · SSE/WS 事件 | 复用 `video_agent` 模板；工具：读写 workspace、触发生成 |
| M12 工作流库 | `CRUD /api/workflow-packs` | 从 canvas group 固化；导入导出 JSON |
| 分享 | `POST /api/canvases/{id}/share` → token 只读链 | 无社区广场也可先做本地只读链接 |
| 快短视频模式 | `POST /api/projects` + `mode=quick_short` | 跳过人工闸门的一键管线 |

---

## 6. 数据模型增量（摘要）

```text
PromptCard += camera_json, style_preset, first_frame, last_frame, reference_mode
VideoTask  += provider, orphaned          # 已做
           += reference_mode, reference_payload
ProjectBible (new)  project_id PK, data JSON
CanvasGraph  (new)  id, project_id, name, graph_json, updated_at
PipelineJob  (new)  id, project_id, status, stage, config_json, error
WorkflowPack (new)  id, name, graph_json, is_public
```

文件布局保持：`projects/{id}/assets|generated|scripts|...`

---

## 7. 前端信息架构（落地后）

```text
项目管理
预处理          # 文档切分 / 转剧本（已有）
资源管理        # 实体卡 + 冲突复核(P1)
视频生成        # P0：镜头列表+监视器+@+参考模式（已删除独立分镜导航）
画布            # P1：节点编辑
提示词管理      # 模板库（已有）
设定 bible      # P1：可挂在项目设置下
设置            # provider / mock 标识（已有）
```

P0 **不新增顶级导航**，已删除独立「分镜台」导航，能力全部强化在「视频生成」页。

---

## 8. 里程碑与依赖

```text
Week 1–2  P0: M3 @引用 + M4 参考模式 + M2 监视器
Week 2–3  P0: M1 镜头体验打磨 + M5 预设
Week 4–6  P1: M7 画布 MVP + M6 往返
Week 5–7  P1: M8 bible + M9 冲突复核
Week 8+   P2: M10 批量 → M11 Agent → M12 工作流/分享
```

依赖顺序：`M3/M4` → `M2` → `M1 体验` → `M7` → `M6` → `M8/M9` → `M10+`。

---

## 9. 明确不做（本阶段）

- 3D 导演台 / 360 全景 / 香蕉分镜品牌玩法  
- TapShow 社区广场、积分体系、团队实时光标协作  
- 多模型智能路由（先手动选 model）  
- 九宫格/二十五宫格等「魔法快捷动作」（P2 再挂到画布 quickActions）

---

## 10. 验收清单（P0 一页）

- [ ] 提示词里 `@实体` 生成视频时 assets 非空  
- [ ] 可选 first/last 帧并写入任务  
- [ ] 任务面板显示 provider；Mock 有醒目标识  
- [ ] 选中镜头可预览最新成片/占位结果  
- [ ] 摄影机或风格预设会改变重跑后的 prompt  
- [ ] 重切分后旧任务仍标记 orphaned（已有则回归）

---

**文档版本**：v1  
**日期**：2026-07-10
