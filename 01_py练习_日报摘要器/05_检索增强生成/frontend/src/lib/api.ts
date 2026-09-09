import { KnowledgePackage, RetrieveRequest, CapabilityRegistry, RetrievalMethodSummary, RetrievalMethodDetail, RetrievePlanResponse } from '../types/retrieval'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/api'

export async function retrieve(request: RetrieveRequest): Promise<KnowledgePackage> {
  const response = await fetch(`${API_BASE}/retrieve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  })
  if (!response.ok) throw new Error((await response.text()) || 'Retrieval failed')
  return response.json()
}

export async function getCapabilities(): Promise<{ backends: CapabilityRegistry[] }> {
  const response = await fetch(`${API_BASE}/capabilities`)
  if (!response.ok) throw new Error('Failed to fetch capabilities')
  return response.json()
}

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`)
  if (!response.ok) throw new Error('Health check failed')
  return response.json()
}

export async function getMethods(): Promise<{ methods: RetrievalMethodSummary[] }> {
  const response = await fetch(`${API_BASE}/methods`)
  if (!response.ok) throw new Error('Failed to fetch methods')
  return response.json()
}

export async function getMethodDetail(methodId: string): Promise<RetrievalMethodDetail> {
  const response = await fetch(`${API_BASE}/methods/${methodId}`)
  if (!response.ok) throw new Error(`Failed to fetch method ${methodId}`)
  return response.json()
}

export async function getOperators(): Promise<{ operators: string[] }> {
  const response = await fetch(`${API_BASE}/operators`)
  if (!response.ok) throw new Error('Failed to fetch operators')
  return response.json()
}

export async function getRetrievePlan(request: RetrieveRequest): Promise<RetrievePlanResponse> {
  const response = await fetch(`${API_BASE}/retrieve/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) throw new Error('Failed to fetch retrieval plan')
  return response.json()
}
