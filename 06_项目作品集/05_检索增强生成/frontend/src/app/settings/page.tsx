import { AppShell } from '@/shared/layout/AppShell'

const settings = [
  ['API 基础地址', 'NEXT_PUBLIC_API_BASE', 'http://127.0.0.1:8000/api'],
  ['PostgreSQL', 'POSTGRES_DSN', 'postgresql://rag_user:rag_pass@localhost:5433/rag_db'],
  ['MinIO', 'MINIO_ENDPOINT', 'localhost:9000'],
  ['LLM API', 'LLM_BASE_URL / LLM_MODEL', '标题、摘要、预设问题'],
  ['Embedding API', 'EMBEDDING_BASE_URL / EMBEDDING_MODEL', '入库向量、查询向量'],
  ['Reranker API', 'RERANKER_BASE_URL / RERANKER_MODEL', '召回后证据重排'],
  ['OCR API', 'OCR_BASE_URL / OCR_MODEL', '扫描页视觉识别，未配置时跳过'],
]

export default function SettingsPage() {
  return (
    <AppShell>
      <div className="mb-5">
        <p className="text-sm font-medium text-sky-700">Settings</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">运行配置</h1>
        <p className="mt-2 text-sm text-slate-600">配置集中在 backend/.env；修改后重启后端生效。</p>
      </div>
      <div className="surface rounded-lg">
        <div className="divide-y divide-slate-200">
          {settings.map(([label, key, value]) => (
            <div key={key} className="grid gap-2 p-5 md:grid-cols-[220px_260px_minmax(0,1fr)]">
              <div className="font-medium text-slate-900">{label}</div>
              <code className="text-sm text-slate-500">{key}</code>
              <code className="rounded-md bg-slate-100 px-2 py-1 text-sm text-slate-700">{value}</code>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  )
}
