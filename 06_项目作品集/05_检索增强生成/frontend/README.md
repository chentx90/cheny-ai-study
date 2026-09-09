# 前端模块

## 页面

| 路由 | 页面 | 说明 |
|:--|:--|:--|
| `/` | 首页 | 导航入口 |
| `/retrieval` | 检索实验台 | 查询 → 方法选择 → Evidence / Asset / DataAsset / Trace 展示 |
| `/ingestion` | 数据接入 | 上传 → 预览 → 入库 → 结果（5 Tab） |
| `/knowledge` | 知识库管理 | 文档列表（筛选/删除）/ Chunk 详情 / 数据资产（3 Tab） |
| `/methods` | 方法详情 | 检索方法列表与步骤配置 |

## 目录

```
src/
  app/
    ingestion/          # page.tsx + 5 个 Tab 组件
      NewImportTab.tsx  # 上传 + 标题输入（placeholder: 留空则自动提取）
      PreviewTab.tsx    # 预览面板（实时刷新 + 显示 content_hash 前8位）
      CommitTab.tsx     # 提交 + 重复冲突弹窗（替换/仍新建/取消）
    knowledge/
    retrieval/
    methods/
  components/
    knowledge/KnowledgeBrowser.tsx
    retrieval/          # RetrievalPlayground + 子组件
  lib/
    api.ts              # 检索相关 fetch（retrieve, getMethods…）
    ingestionApi.ts     # commitJob(jobId, onDuplicate) 接入管道 fetch
    knowledgeApi.ts     # 知识管理 fetch
    config.ts           # API_BASE（NEXT_PUBLIC_API_BASE，默认 localhost:8000/api）
  types/
    ingestion.ts        # IngestionJob(id), IngestionUpload, IngestionPreview…
    retrieval.ts        # KnowledgePackage, EvidenceItem, RetrieveRequest…
    knowledge.ts        # KnowledgeDoc, KnowledgeChunk, KnowledgeDataAsset
```

## 接入管道交互流程

```
上传文件（NewImportTab）
  │  POST /ingestion/uploads
  ▼
创建预览任务
  │  POST /ingestion/jobs/preview
  ▼
watchPreview()  ─── 轮询 GET /ingestion/jobs/{id}
  │  每 tick 实时更新 PreviewTab 面板
  ▼
用户确认 → handleCommit()
  │  POST /ingestion/jobs/{id}/commit  {on_duplicate: "block"}
  │
  ├─ 200 → 进度轮询 pollUntilTerminal() → 结果页
  └─ 409 → 弹窗（替换 / 仍新建 / 取消）
             │
             └─ 重提交 {on_duplicate: "replace" | "new"}
```

## 关键设计

- **单一 `id` 字段**：`IngestionJob.id: string`（已去除旧 `job_id` 双字段）
- **轮询终止**：`pollUntilTerminal()` 返回 Promise，commit 等待到终态后再取结果，无 `setTimeout` 竞态
- **预览自刷新**：创建预览任务后 `watchPreview()` 在轮询 tick 中实时更新预览面板
- **类型归位**：所有 domain 类型在 `types/` 下，lib/ 只做 fetch 封装
- **去重处理**：捕获 409 后保留 `existing_id / existing_title`，弹窗中展示冲突文档信息

## 开发

```bash
cd frontend
npm run dev    # http://localhost:3000
npm run build  # 类型检查 + 生产构建
```
