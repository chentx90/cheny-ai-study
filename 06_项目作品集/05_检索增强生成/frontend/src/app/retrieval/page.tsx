import { AppShell } from '@/shared/layout/AppShell'
import { RetrievalWorkspace } from '@/features/retrieval/RetrievalWorkspace'

export default function RetrievalPage() {
  return (
    <AppShell>
      <div className="mb-5">
        <p className="text-sm font-medium text-sky-700">Retrieval</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">检索调试</h1>
        <p className="mt-2 text-sm text-slate-600">验证召回证据、分数、执行轨迹和业务域过滤。</p>
      </div>
      <RetrievalWorkspace />
    </AppShell>
  )
}
