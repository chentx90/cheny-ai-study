import { AppShell } from '@/shared/layout/AppShell'
import { KnowledgeWorkspace } from '@/features/knowledge/KnowledgeWorkspace'

export default function KnowledgePage() {
  return (
    <AppShell>
      <div className="mb-5">
        <p className="text-sm font-medium text-sky-700">Knowledge</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">知识库浏览</h1>
        <p className="mt-2 text-sm text-slate-600">查看已批准文档、分块内容和结构化数据资产。</p>
      </div>
      <KnowledgeWorkspace />
    </AppShell>
  )
}
