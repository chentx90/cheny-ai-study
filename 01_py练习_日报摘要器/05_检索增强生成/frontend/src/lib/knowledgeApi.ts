import { API_BASE } from './config'
import type { KnowledgeDoc, KnowledgeChunk, KnowledgeDataAsset } from '../types/knowledge'

export type { KnowledgeDoc, KnowledgeChunk, KnowledgeDataAsset }

async function req(path: string, opts?: RequestInit) {
  const r = await fetch(`${API_BASE}${path}`, opts)
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return r.json()
}

export const listDocuments = (p?: { keyword?: string; business_domain?: string }) => {
  const q = new URLSearchParams()
  if (p?.keyword) q.set('keyword', p.keyword)
  if (p?.business_domain) q.set('business_domain', p.business_domain)
  return req(`/knowledge/documents?${q}`) as Promise<{ documents: KnowledgeDoc[] }>
}

export const listChunks = (docId: string) =>
  req(`/knowledge/documents/${encodeURIComponent(docId)}/chunks`) as Promise<{ chunks: KnowledgeChunk[] }>

export const deleteDocument = (docId: string) =>
  req(`/knowledge/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' })

export const listDataAssets = (p?: { keyword?: string; business_domain?: string }) => {
  const q = new URLSearchParams()
  if (p?.keyword) q.set('keyword', p.keyword)
  if (p?.business_domain) q.set('business_domain', p.business_domain)
  return req(`/knowledge/data-assets?${q}`) as Promise<{ data_assets: KnowledgeDataAsset[] }>
}

export const deleteDataAsset = (id: string) =>
  req(`/knowledge/data-assets/${encodeURIComponent(id)}`, { method: 'DELETE' })
