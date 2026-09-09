import { API_BASE } from './config'
import type {
  ApprovalResult,
  FileAsset,
  IngestionJob,
  IngestionJobError,
  IngestionPreview,
  IngestionSourceType,
  IngestionUpload,
  ParsedDocumentReview,
} from '@/types/ingestion'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) throw new Error((await res.text()) || res.statusText)
  return res.json()
}

export async function uploadRawFile(file: File, businessDomain = 'general'): Promise<IngestionUpload> {
  const form = new FormData()
  form.append('file', file)
  return request(`/file-assets/upload?business_domain=${encodeURIComponent(businessDomain)}`, {
    method: 'POST',
    body: form,
  })
}

export const uploadFile = uploadRawFile

export function listFileAssets(params?: { limit?: number; business_domain?: string }) {
  const q = new URLSearchParams()
  q.set('limit', String(params?.limit ?? 50))
  if (params?.business_domain) q.set('business_domain', params.business_domain)
  return request<{ file_assets: FileAsset[] }>(`/file-assets?${q}`)
}

export function importBatch(payload: { root_path: string; business_domain?: string; batch_name?: string }) {
  return request('/file-assets/import-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function listUploads(limit = 50) {
  return request<{ uploads: IngestionUpload[] }>(`/ingestion/uploads?limit=${limit}`)
}

export function createPreviewJob(payload: {
  upload_id: string
  source_type: IngestionSourceType | string
  title?: string
  business_domain?: string
  doc_type?: string
  version?: string
  options?: Record<string, unknown>
}) {
  return request<IngestionJob>('/ingestion/jobs/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function createPreviewJobFromAsset(fileAssetId: string, payload: {
  source_type: IngestionSourceType | string
  title?: string
  business_domain?: string
  doc_type?: string
  version?: string
  options?: Record<string, unknown>
}) {
  return request<IngestionJob>(`/file-assets/${encodeURIComponent(fileAssetId)}/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function createPreviewJobsFromAssets(payload: {
  file_asset_ids: string[]
  business_domain?: string
  doc_type?: string
  version?: string
  options?: Record<string, unknown>
}) {
  return request<{ jobs: IngestionJob[]; failed: Array<{ file_asset_id: string; file?: string; error: string }> }>('/file-assets/preview-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function listJobs(status?: string, limit = 50) {
  const q = new URLSearchParams()
  q.set('limit', String(limit))
  if (status) q.set('status', status)
  return request<{ jobs: IngestionJob[] }>(`/ingestion/jobs?${q}`)
}

export function getJob(jobId: string) {
  return request<IngestionJob>(`/ingestion/jobs/${encodeURIComponent(jobId)}`)
}

export function getJobPreview(jobId: string) {
  return request<IngestionPreview>(`/ingestion/jobs/${encodeURIComponent(jobId)}/preview`)
}

export function getReview(parsedDocumentId: string) {
  return request<ParsedDocumentReview>(`/parsed-documents/${encodeURIComponent(parsedDocumentId)}/review`)
}

export function approveReview(parsedDocumentId: string, onDuplicate: 'block' | 'replace' | 'new' = 'block') {
  return request<ApprovalResult>(`/parsed-documents/${encodeURIComponent(parsedDocumentId)}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ on_duplicate: onDuplicate }),
  })
}

export function rejectReview(parsedDocumentId: string, reason = '') {
  return request<ParsedDocumentReview>(`/parsed-documents/${encodeURIComponent(parsedDocumentId)}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
}

export function deleteReview(parsedDocumentId: string) {
  return request<{ deleted: boolean }>(`/parsed-documents/${encodeURIComponent(parsedDocumentId)}`, { method: 'DELETE' })
}

export function deleteFileAsset(fileAssetId: string) {
  return request<{ deleted: boolean }>(`/file-assets/${encodeURIComponent(fileAssetId)}`, { method: 'DELETE' })
}

export function getJobErrors(jobId: string) {
  return request<{ errors: IngestionJobError[] }>(`/ingestion/jobs/${encodeURIComponent(jobId)}/errors`)
}

export function deleteJob(jobId: string) {
  return request<{ deleted: boolean }>(`/ingestion/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
}

export function retryJob(jobId: string) {
  return request<IngestionJob>(`/ingestion/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' })
}
