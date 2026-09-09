'use client'

import { useEffect, useState } from 'react'
import { getMethodDetail, getMethods } from '@/lib/api'
import type { RetrievalMethodDetail, RetrievalMethodSummary } from '@/types/retrieval'
import { AppShell } from '@/shared/layout/AppShell'
import { Badge } from '@/shared/ui/Badge'
import { Button } from '@/shared/ui/Button'

export default function MethodsPage() {
  const [methods, setMethods] = useState<RetrievalMethodSummary[]>([])
  const [detail, setDetail] = useState<RetrievalMethodDetail | null>(null)
  const [error, setError] = useState('')

  async function load() {
    try {
      const data = await getMethods()
      setMethods(data.methods)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载方法失败')
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function open(id: string) {
    try {
      setDetail(await getMethodDetail(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载方法详情失败')
    }
  }

  return (
    <AppShell>
      <div className="mb-5">
        <p className="text-sm font-medium text-sky-700">Methods</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">检索方法配置</h1>
        <p className="mt-2 text-sm text-slate-600">查看后端 methods JSON 定义和每个执行步骤。</p>
      </div>
      {error && <div className="mb-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="surface rounded-lg p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-950">方法列表</h2>
            <Button onClick={load}>刷新</Button>
          </div>
          <div className="space-y-2">
            {methods.map((method) => (
              <button key={method.method_id} onClick={() => open(method.method_id)} className="block w-full rounded-md border border-slate-200 p-3 text-left hover:bg-slate-50">
                <div className="font-mono text-xs text-slate-500">{method.method_id}</div>
                <p className="mt-1 text-sm text-slate-700">{method.description || '-'}</p>
              </button>
            ))}
          </div>
        </div>
        <div className="surface rounded-lg p-5">
          <h2 className="text-base font-semibold text-slate-950">{detail?.method_id || '选择方法查看详情'}</h2>
          <div className="mt-4 space-y-3">
            {detail?.steps?.map((step, index) => (
              <div key={`${step.name}-${index}`} className="rounded-md border border-slate-200 p-4">
                <div className="flex items-center justify-between">
                  <div className="font-medium text-slate-900">{index + 1}. {step.name}</div>
                  <Badge tone="blue">{step.operator}</Badge>
                </div>
                <div className="mt-2 text-sm text-slate-500">backend: {step.backend}</div>
                <pre className="mt-3 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(step.params || {}, null, 2)}</pre>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  )
}
