'use client'

import { useEffect, useState } from 'react'
import { getMetrics, runEvaluation, type EvalMetrics, type EvalResult } from '@/lib/evaluationApi'
import { AppShell } from '@/shared/layout/AppShell'
import { Badge } from '@/shared/ui/Badge'
import { Button } from '@/shared/ui/Button'

export default function EvaluationPage() {
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState<EvalResult[]>([])
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getMetrics().then(setMetrics).catch(() => {})
  }, [])

  async function run() {
    setRunning(true)
    setError('')
    try {
      const data = await runEvaluation()
      setResults(data)
      setMetrics({
        total: data.length,
        hit1: data.filter((item) => item.hit1).length / Math.max(data.length, 1),
        hit3: data.filter((item) => item.hit3).length / Math.max(data.length, 1),
        hit5: data.filter((item) => item.hit5).length / Math.max(data.length, 1),
        mrr: data.reduce((sum, item) => sum + item.mrr, 0) / Math.max(data.length, 1),
        avg_latency: data.reduce((sum, item) => sum + item.latency_ms, 0) / Math.max(data.length, 1),
        report_path: metrics?.report_path,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : '评估失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <AppShell>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-sky-700">Evaluation</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">检索质量评估</h1>
          <p className="mt-2 text-sm text-slate-600">批量运行测试问题，检查召回命中率、排名、MRR 和延迟。</p>
        </div>
        <Button onClick={run} variant="primary" disabled={running}>
          {running ? '评估中' : '运行评估'}
        </Button>
      </div>

      {error && <div className="mb-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {metrics && (
        <div className="mb-5 grid gap-4 md:grid-cols-5">
          {[
            ['Total', metrics.total],
            ['Hit@1', `${(metrics.hit1 * 100).toFixed(1)}%`],
            ['Hit@3', `${(metrics.hit3 * 100).toFixed(1)}%`],
            ['MRR', metrics.mrr.toFixed(3)],
            ['Latency', `${metrics.avg_latency.toFixed(0)} ms`],
          ].map(([label, value]) => (
            <div key={label} className="surface rounded-lg p-4">
              <div className="text-xs text-slate-500">{label}</div>
              <div className="mt-2 text-xl font-semibold text-slate-950">{value}</div>
            </div>
          ))}
        </div>
      )}

      {metrics?.report_path && (
        <div className="mb-5 rounded-md border border-slate-200 bg-slate-50 px-4 py-3 font-mono text-xs text-slate-600">
          {metrics.report_path}
        </div>
      )}

      <div className="surface overflow-hidden rounded-lg">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Case</th>
              <th className="px-4 py-3 text-left">Query</th>
              <th className="px-4 py-3 text-left">Hit@1</th>
              <th className="px-4 py-3 text-left">Hit@3</th>
              <th className="px-4 py-3 text-left">Hit@5</th>
              <th className="px-4 py-3 text-left">Rank</th>
              <th className="px-4 py-3 text-left">Reason</th>
              <th className="px-4 py-3 text-right">Latency</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {results.map((row) => (
              <tr key={row.case_id}>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{row.case_id}</td>
                <td className="max-w-[420px] truncate px-4 py-3 text-slate-900">{row.query}</td>
                <td className="px-4 py-3"><Badge tone={row.hit1 ? 'green' : 'red'}>{row.hit1 ? 'yes' : 'no'}</Badge></td>
                <td className="px-4 py-3"><Badge tone={row.hit3 ? 'green' : 'red'}>{row.hit3 ? 'yes' : 'no'}</Badge></td>
                <td className="px-4 py-3"><Badge tone={row.hit5 ? 'green' : 'red'}>{row.hit5 ? 'yes' : 'no'}</Badge></td>
                <td className="px-4 py-3 text-slate-700">{row.matched_rank || '-'}</td>
                <td className="max-w-[260px] truncate px-4 py-3 text-slate-600">{row.matched_reason || '-'}</td>
                <td className="px-4 py-3 text-right text-slate-600">{row.latency_ms} ms</td>
              </tr>
            ))}
            {results.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-sm text-slate-500">
                  点击运行评估后查看测试结果。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </AppShell>
  )
}
