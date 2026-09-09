import { API_BASE } from './config'

export interface EvalResult {
  case_id: string
  query: string
  hit1: boolean
  hit3: boolean
  hit5: boolean
  mrr: number
  matched_rank?: number | null
  matched_reason?: string | null
  latency_ms: number
}

export interface EvalMetrics {
  total: number
  hit1: number
  hit3: number
  hit5: number
  mrr: number
  avg_latency: number
  report_path?: string
}

export async function runEvaluation(): Promise<EvalResult[]> {
  const response = await fetch(`${API_BASE}/evaluation/run`, {
    method: 'POST',
  })
  if (!response.ok) throw new Error('Evaluation failed')
  return response.json()
}

export async function getMetrics(): Promise<EvalMetrics> {
  const response = await fetch(`${API_BASE}/evaluation/metrics`)
  if (!response.ok) throw new Error('Failed to fetch metrics')
  return response.json()
}
