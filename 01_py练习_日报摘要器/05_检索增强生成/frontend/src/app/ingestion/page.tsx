import { AppShell } from '@/shared/layout/AppShell'
import { IngestionWorkspace } from '@/features/ingestion/IngestionWorkspace'

export default function IngestionPage() {
  return (
    <AppShell>
      <div className="mb-5">
        <p className="text-sm font-medium text-sky-700">Ingestion</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">原始文件导入与审核</h1>
        <p className="mt-2 text-sm text-slate-600">先保存原始文件，再生成可审阅分块，批准后写入知识库并触发向量流程。</p>
      </div>
      <IngestionWorkspace />
    </AppShell>
  )
}
