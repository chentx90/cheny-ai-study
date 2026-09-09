'use client'

import { useState } from 'react'
import { getMethods, retrieve } from '@/lib/api'
import type { KnowledgePackage, RetrievalMethodSummary, RetrievalMode } from '@/types/retrieval'
import { Badge } from '@/shared/ui/Badge'
import { Button } from '@/shared/ui/Button'
import { Field, SelectInput, TextArea, TextInput } from '@/shared/ui/Field'

const modes: RetrievalMode[] = ['fast', 'balanced', 'reliable', 'deep']

export function RetrievalWorkspace() {
  const [query, setQuery] = useState('磷酸铁生产系统清理规范中，清理验收方法有哪些？')
  const [mode, setMode] = useState<RetrievalMode>('balanced')
  const [businessDomain, setBusinessDomain] = useState('')
  const [result, setResult] = useState<KnowledgePackage | null>(null)
  const [methods, setMethods] = useState<RetrievalMethodSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    setLoading(true)
    setError('')
    try {
      const data = await retrieve({
        query,
        mode,
        constraints: businessDomain ? { business_domain: businessDomain } : undefined,
      })
      setResult(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : '检索失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadMethods() {
    try {
      const data = await getMethods()
      setMethods(data.methods)
    } catch {
      setMethods([])
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
      <div className="space-y-5">
        <div className="surface rounded-lg p-5">
          <h2 className="text-base font-semibold text-slate-950">检索请求</h2>
          <div className="mt-4 space-y-4">
            <Field label="问题">
              <TextArea rows={6} value={query} onChange={(event) => setQuery(event.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="模式">
                <SelectInput value={mode} onChange={(event) => setMode(event.target.value as RetrievalMode)}>
                  {modes.map((item) => <option key={item} value={item}>{item}</option>)}
                </SelectInput>
              </Field>
              <Field label="业务域">
                <TextInput value={businessDomain} onChange={(event) => setBusinessDomain(event.target.value)} placeholder="可选" />
              </Field>
            </div>
            <Button onClick={run} variant="primary" disabled={loading || !query.trim()} className="w-full">
              {loading ? '检索中' : '运行检索'}
            </Button>
          </div>
        </div>

        <div className="surface rounded-lg p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-950">可用方法</h2>
            <Button onClick={loadMethods}>加载</Button>
          </div>
          <div className="mt-4 space-y-3">
            {methods.map((method) => (
              <div key={method.method_id} className="rounded-md border border-slate-200 p-3">
                <div className="font-mono text-xs text-slate-500">{method.method_id}</div>
                <p className="mt-1 text-sm text-slate-700">{method.description || '-'}</p>
              </div>
            ))}
            {methods.length === 0 && <p className="text-sm text-slate-500">点击加载查看后端方法配置。</p>}
          </div>
        </div>
      </div>

      <div className="space-y-5">
        {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        <div className="surface rounded-lg">
          <div className="border-b border-slate-200 p-5">
            <h2 className="text-base font-semibold text-slate-950">证据结果</h2>
            <p className="mt-1 text-sm text-slate-500">{result ? `${result.evidence?.length || 0} 条 evidence` : '运行检索后查看证据片段。'}</p>
          </div>
          <div className="space-y-4 p-5">
            {result?.evidence?.map((item) => (
              <div key={item.chunk_id} className="rounded-lg border border-slate-200 p-4">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium text-slate-950">{item.title_context || item.section_path || item.chunk_id}</div>
                  <Badge tone="blue">{(item.score * 100).toFixed(1)}%</Badge>
                </div>
                <div className="mb-3 text-xs text-slate-500">{item.section_path}</div>
                <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{item.content}</p>
              </div>
            ))}
            {result && (!result.evidence || result.evidence.length === 0) && <p className="text-sm text-slate-500">没有返回证据。</p>}
          </div>
        </div>

        {result?.retrieval_trace && (
          <div className="surface rounded-lg p-5">
            <h2 className="text-base font-semibold text-slate-950">执行轨迹</h2>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs text-slate-500">Latency</div>
                <div className="mt-1 font-semibold text-slate-950">{result.retrieval_trace.latency_ms} ms</div>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs text-slate-500">Strategies</div>
                <div className="mt-1 text-sm text-slate-700">{result.retrieval_trace.strategies?.join(', ') || '-'}</div>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs text-slate-500">Backends</div>
                <div className="mt-1 text-sm text-slate-700">{result.retrieval_trace.backends?.join(', ') || '-'}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
