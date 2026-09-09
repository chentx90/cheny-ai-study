'use client'

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  approveReview,
  createPreviewJob,
  createPreviewJobFromAsset,
  createPreviewJobsFromAssets,
  deleteFileAsset,
  deleteJob,
  deleteReview,
  getJobErrors,
  getJob,
  getReview,
  importBatch,
  listFileAssets,
  listJobs,
  listUploads,
  rejectReview,
  uploadRawFile,
} from '@/lib/ingestionApi'
import type { FileAsset, IngestionJob, IngestionSourceType, IngestionUpload, ParsedDocumentReview } from '@/types/ingestion'
import { Badge } from '@/shared/ui/Badge'
import { Button } from '@/shared/ui/Button'
import { Field, SelectInput, TextArea, TextInput } from '@/shared/ui/Field'
import { fileTypeFromName, formatBytes, formatDateTime, parseJsonField } from '@/shared/lib/format'
import { cn } from '@/shared/lib/cn'

const sourceTypes: IngestionSourceType[] = ['pdf', 'excel', 'markdown', 'docx', 'pptx', 'txt', 'csv', 'json']

function statusTone(status?: string) {
  if (status === 'completed' || status === 'approved' || status === 'uploaded') return 'green'
  if (status === 'failed' || status === 'rejected') return 'red'
  if (status === 'parsing' || status === 'pending' || status === 'draft') return 'amber'
  if (status === 'embedding' || status === 'writing') return 'violet'
  return 'slate'
}

function jobResult(job?: IngestionJob) {
  return parseJsonField<Record<string, unknown>>(job?.result, {})
}

function sourceTypeFor(asset?: FileAsset): IngestionSourceType {
  const detected = fileTypeFromName(asset?.original_filename)
  return sourceTypes.includes(detected as IngestionSourceType) ? (detected as IngestionSourceType) : 'pdf'
}

function selectedCountLabel(count: number) {
  return count > 0 ? `已选 ${count}` : '未选择'
}

export function IngestionWorkspace() {
  const [assets, setAssets] = useState<FileAsset[]>([])
  const [uploads, setUploads] = useState<IngestionUpload[]>([])
  const [jobs, setJobs] = useState<IngestionJob[]>([])
  const [selectedAssetId, setSelectedAssetId] = useState('')
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
  const [selectedJobId, setSelectedJobId] = useState('')
  const [review, setReview] = useState<ParsedDocumentReview | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId)
  const selectedUpload = uploads.find((upload) => upload.file_asset_id === selectedAssetId)
  const selectedJob = jobs.find((job) => job.job_id === selectedJobId)
  const selectedJobResult = jobResult(selectedJob)
  const parsedDocumentId = (selectedJobResult.parsed_document_id as string | undefined) || review?.id
  const selectedAssets = useMemo(() => assets.filter((asset) => selectedAssetIds.includes(asset.id)), [assets, selectedAssetIds])

  const refresh = useCallback(async () => {
    const [assetData, uploadData, jobData] = await Promise.all([listFileAssets({ limit: 300 }), listUploads(300), listJobs(undefined, 300)])
    setAssets(assetData.file_assets)
    setUploads(uploadData.uploads)
    setJobs(jobData.jobs)
  }, [])

  useEffect(() => {
    refresh().catch((e: Error) => setError(e.message))
  }, [refresh])

  useEffect(() => {
    if (!selectedJobId) return
    const timer = window.setInterval(async () => {
      const job = await getJob(selectedJobId).catch(() => null)
      if (!job) return
      setJobs((prev) => prev.map((item) => (item.job_id === job.job_id ? job : item)))
      if (['completed', 'failed', 'cancelled'].includes(job.status)) window.clearInterval(timer)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [selectedJobId])

  const stats = useMemo(() => {
    const completed = jobs.filter((job) => job.status === 'completed').length
    const failed = jobs.filter((job) => job.status === 'failed').length
    const drafts = jobs.filter((job) => job.mode === 'preview' && job.status === 'completed').length
    return { assets: assets.length, completed, failed, drafts }
  }, [assets, jobs])

  function toggleAsset(asset: FileAsset) {
    setSelectedAssetId(asset.id)
    setSelectedAssetIds((prev) => (prev.includes(asset.id) ? prev.filter((id) => id !== asset.id) : [...prev, asset.id]))
  }

  function selectAllAssets() {
    setSelectedAssetIds((prev) => (prev.length === assets.length ? [] : assets.map((asset) => asset.id)))
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const form = new FormData(event.currentTarget)
      const file = form.get('file') as File | null
      const domain = String(form.get('business_domain') || 'general')
      if (!file || !file.name) throw new Error('请选择文件')
      const uploaded = await uploadRawFile(file, domain)
      await refresh()
      const id = uploaded.file_asset_id || uploaded.file_asset?.id || ''
      setSelectedAssetId(id)
      setSelectedAssetIds((prev) => (id && !prev.includes(id) ? [id, ...prev] : prev))
      setMessage(`已保存原始文件：${uploaded.file_name}`)
      event.currentTarget.reset()
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const form = new FormData(event.currentTarget)
      const result = await importBatch({
        root_path: String(form.get('root_path') || ''),
        business_domain: String(form.get('business_domain') || 'general'),
        batch_name: String(form.get('batch_name') || ''),
      }) as { imported?: FileAsset[]; failed?: Array<{ path: string; error: string }> }
      await refresh()
      const importedIds = (result.imported || []).map((asset) => asset.id)
      setSelectedAssetIds(importedIds)
      setSelectedAssetId(importedIds[0] || '')
      setMessage(`批量目录已导入 ${importedIds.length} 个原始文件${result.failed?.length ? `，失败 ${result.failed.length} 个` : ''}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '批量导入失败')
    } finally {
      setBusy(false)
    }
  }

  function parsePayloadFromForm(form: FormData, asset: FileAsset) {
    const sourceType = String(form.get('source_type') || sourceTypeFor(asset))
    return {
      source_type: sourceType,
      title: String(form.get('title') || asset.original_filename),
      business_domain: String(form.get('business_domain') || asset.business_domain || 'general'),
      doc_type: String(form.get('doc_type') || sourceType),
      version: String(form.get('version') || '1.0'),
      options: {
        chunk_size: Number(form.get('chunk_size') || 600),
        chunk_overlap: Number(form.get('chunk_overlap') || 80),
        excel_mode: sourceType === 'excel' ? 'text' : undefined,
      },
    }
  }

  async function handleParse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedAsset) return
    setBusy(true)
    setError('')
    setMessage('')
    setReview(null)
    try {
      const form = new FormData(event.currentTarget)
      const payload = parsePayloadFromForm(form, selectedAsset)
      const uploadId = String(form.get('upload_id') || '')
      const job = uploadId
        ? await createPreviewJob({ upload_id: uploadId, ...payload })
        : await createPreviewJobFromAsset(selectedAsset.id, payload)
      setSelectedJobId(job.job_id)
      await refresh()
      setMessage('解析任务已创建，完成后可进入审核')
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建解析任务失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleBatchParse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedAssets.length) return
    setBusy(true)
    setError('')
    setMessage('')
    setReview(null)
    try {
      const form = new FormData(event.currentTarget)
      const result = await createPreviewJobsFromAssets({
        file_asset_ids: selectedAssets.map((asset) => asset.id),
        business_domain: String(form.get('business_domain') || selectedAssets[0]?.business_domain || 'general'),
        doc_type: String(form.get('doc_type') || ''),
        version: String(form.get('version') || '1.0'),
        options: {
          chunk_size: Number(form.get('chunk_size') || 600),
          chunk_overlap: Number(form.get('chunk_overlap') || 80),
        },
      })
      await refresh()
      setSelectedJobId(result.jobs[0]?.job_id || '')
      setMessage(`已创建 ${result.jobs.length} 个解析任务${result.failed.length ? `，失败 ${result.failed.length} 个` : ''}`)
      if (result.failed.length) setError(result.failed.map((item) => `${item.file || item.file_asset_id}: ${item.error}`).join('\n'))
    } catch (e) {
      setError(e instanceof Error ? e.message : '批量解析失败')
    } finally {
      setBusy(false)
    }
  }

  async function loadReviewFromJob(job: IngestionJob) {
    const result = jobResult(job)
    const id = result.parsed_document_id as string | undefined
    if (!id) {
      setError('该任务还没有 parsed_document_id')
      return
    }
    setBusy(true)
    setError('')
    try {
      setReview(await getReview(id))
      setSelectedJobId(job.job_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载审核内容失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleApprove(mode: 'block' | 'replace' | 'new') {
    if (!parsedDocumentId) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const result = await approveReview(parsedDocumentId, mode)
      setMessage(`已批准入库：${result.chunks} 个 chunk，embedding job ${result.embedding_job_id}`)
      setReview(await getReview(parsedDocumentId))
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '批准失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleReject(reason: string) {
    if (!parsedDocumentId) return
    setBusy(true)
    setError('')
    try {
      setReview(await rejectReview(parsedDocumentId, reason))
      setMessage('已拒绝该解析草稿')
    } catch (e) {
      setError(e instanceof Error ? e.message : '拒绝失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteReview() {
    if (!parsedDocumentId) return
    if (!window.confirm('删除该解析草稿和关联解析任务？原始文件会保留。')) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await deleteReview(parsedDocumentId)
      setReview(null)
      setSelectedJobId('')
      await refresh()
      setMessage('已删除解析草稿')
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除解析草稿失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteAsset(asset: FileAsset) {
    if (!window.confirm(`删除原始文件资产「${asset.original_filename}」及其未入库解析记录？`)) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await deleteFileAsset(asset.id)
      setSelectedAssetIds((prev) => prev.filter((id) => id !== asset.id))
      if (selectedAssetId === asset.id) setSelectedAssetId('')
      await refresh()
      setMessage('已删除原始文件资产')
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除原始文件失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteJob(job: IngestionJob) {
    if (!window.confirm(`删除解析任务「${job.title || job.job_id}」及其未批准草稿？`)) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await deleteJob(job.job_id)
      if (selectedJobId === job.job_id) {
        setSelectedJobId('')
        setReview(null)
      }
      await refresh()
      setMessage('已删除解析任务')
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除解析任务失败')
    } finally {
      setBusy(false)
    }
  }

  async function showJobErrors(job: IngestionJob) {
    setBusy(true)
    setError('')
    try {
      const data = await getJobErrors(job.job_id)
      const text = data.errors.map((item) => `[${item.stage}] ${item.message}`).join('\n')
      setError(text || '该任务没有错误详情')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载错误详情失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <section className="grid gap-4 lg:grid-cols-4">
        {[
          ['原始文件', stats.assets],
          ['完成任务', stats.completed],
          ['待审草稿', stats.drafts],
          ['失败任务', stats.failed],
        ].map(([label, value]) => (
          <div key={label} className="surface rounded-lg p-4">
            <div className="text-sm text-slate-500">{label}</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{value}</div>
          </div>
        ))}
      </section>

      {(error || message) && (
        <div className={cn('whitespace-pre-wrap rounded-md border px-4 py-3 text-sm', error ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700')}>
          {error || message}
        </div>
      )}

      <section className="grid gap-5 xl:grid-cols-[390px_minmax(0,1fr)]">
        <div className="space-y-5">
          <div className="surface rounded-lg p-4">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-950">原始文件资产</h2>
              <Button onClick={() => refresh()} disabled={busy}>刷新</Button>
            </div>
            <form onSubmit={handleUpload} className="space-y-3">
              <Field label="业务域">
                <TextInput name="business_domain" defaultValue="general" />
              </Field>
              <Field label="上传文件">
                <input name="file" type="file" required className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white" />
              </Field>
              <Button type="submit" variant="primary" disabled={busy} className="w-full">保存原始文件</Button>
            </form>
          </div>

          <div className="surface rounded-lg p-4">
            <h2 className="mb-4 text-base font-semibold text-slate-950">多层目录导入</h2>
            <form onSubmit={handleBatch} className="space-y-3">
              <Field label="根目录路径">
                <TextInput name="root_path" placeholder="/path/to/your/documents" />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="业务域">
                  <TextInput name="business_domain" defaultValue="general" />
                </Field>
                <Field label="批次名">
                  <TextInput name="batch_name" placeholder="可选" />
                </Field>
              </div>
              <Button type="submit" disabled={busy} className="w-full">导入目录</Button>
            </form>
          </div>

          <div className="surface max-h-[560px] overflow-hidden rounded-lg">
            <div className="flex items-center justify-between border-b border-slate-200 p-4">
              <div>
                <h2 className="text-base font-semibold text-slate-950">最近文件</h2>
                <div className="mt-1 text-xs text-slate-500">{selectedCountLabel(selectedAssetIds.length)}</div>
              </div>
              <Button onClick={selectAllAssets} disabled={busy || !assets.length}>{selectedAssetIds.length === assets.length && assets.length ? '清空' : '全选'}</Button>
            </div>
            <div className="max-h-[480px] overflow-auto p-2">
              {assets.map((asset) => {
                const checked = selectedAssetIds.includes(asset.id)
                return (
                  <div
                    key={asset.id}
                    className={cn('mb-2 grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 rounded-md border p-3 text-sm transition', selectedAssetId === asset.id ? 'border-sky-300 bg-sky-50' : 'border-slate-200 hover:bg-slate-50')}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleAsset(asset)}
                      className="h-4 w-4 rounded border-slate-300 text-slate-900"
                      aria-label={`选择 ${asset.original_filename}`}
                    />
                    <button type="button" onClick={() => setSelectedAssetId(asset.id)} className="min-w-0 text-left">
                      <div className="truncate font-medium text-slate-900">{asset.original_filename}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                        <span>{formatBytes(asset.file_size)}</span>
                        <span>{asset.storage_backend}</span>
                        <span>{sourceTypeFor(asset)}</span>
                        <Badge tone={statusTone(asset.status)}>{asset.status}</Badge>
                      </div>
                    </button>
                    <Button type="button" variant="ghost" onClick={() => handleDeleteAsset(asset)} disabled={busy}>删除</Button>
                  </div>
                )
              })}
              {assets.length === 0 && <div className="p-6 text-center text-sm text-slate-500">暂无原始文件。</div>}
            </div>
          </div>
        </div>

        <div className="space-y-5">
          <div className="surface rounded-lg p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-950">批量解析</h2>
                <p className="text-sm text-slate-500">按文件后缀自动选择 PDF、Excel、Markdown、DOCX、PPTX、TXT、CSV 或 JSON。</p>
              </div>
              <Badge tone="blue">{selectedCountLabel(selectedAssetIds.length)}</Badge>
            </div>
            <form onSubmit={handleBatchParse} className="grid gap-4 lg:grid-cols-6">
              <Field label="业务域">
                <TextInput name="business_domain" defaultValue={selectedAssets[0]?.business_domain || 'general'} />
              </Field>
              <Field label="文档类型">
                <TextInput name="doc_type" placeholder="默认按文件类型" />
              </Field>
              <Field label="版本">
                <TextInput name="version" defaultValue="1.0" />
              </Field>
              <Field label="Chunk 大小">
                <TextInput name="chunk_size" type="number" defaultValue={600} />
              </Field>
              <Field label="重叠">
                <TextInput name="chunk_overlap" type="number" defaultValue={80} />
              </Field>
              <div className="flex items-end">
                <Button type="submit" variant="primary" disabled={busy || !selectedAssets.length} className="w-full">批量生成草稿</Button>
              </div>
            </form>
          </div>

          <div className="surface rounded-lg p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-slate-950">单文件解析</h2>
                <p className="text-sm text-slate-500">需要覆盖自动判断时，可以手动选择类型。</p>
              </div>
              {selectedAsset && <Badge tone="blue">{selectedAsset.file_ext || fileTypeFromName(selectedAsset.original_filename)}</Badge>}
            </div>
            {selectedAsset ? (
              <form onSubmit={handleParse} className="grid gap-4 lg:grid-cols-6">
                <input type="hidden" name="upload_id" value={selectedUpload?.upload_id || ''} />
                <Field label="文件">
                  <TextInput value={selectedAsset.original_filename} readOnly />
                </Field>
                <Field label="类型">
                  <SelectInput name="source_type" defaultValue={sourceTypeFor(selectedAsset)}>
                    {sourceTypes.map((type) => <option key={type} value={type}>{type}</option>)}
                  </SelectInput>
                </Field>
                <Field label="标题">
                  <TextInput name="title" defaultValue={selectedAsset.original_filename.replace(/\.[^.]+$/, '')} />
                </Field>
                <Field label="业务域">
                  <TextInput name="business_domain" defaultValue={selectedAsset.business_domain || 'general'} />
                </Field>
                <Field label="文档类型">
                  <TextInput name="doc_type" defaultValue={sourceTypeFor(selectedAsset)} />
                </Field>
                <Field label="版本">
                  <TextInput name="version" defaultValue="1.0" />
                </Field>
                <Field label="Chunk 大小">
                  <TextInput name="chunk_size" type="number" defaultValue={600} />
                </Field>
                <Field label="重叠">
                  <TextInput name="chunk_overlap" type="number" defaultValue={80} />
                </Field>
                <div className="flex items-end lg:col-span-4">
                  <Button type="submit" variant="primary" disabled={busy} className="w-full">
                    生成解析草稿
                  </Button>
                </div>
              </form>
            ) : (
              <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">请选择左侧原始文件。</div>
            )}
          </div>

          <div className="surface rounded-lg">
            <div className="flex items-center justify-between border-b border-slate-200 p-4">
              <h2 className="text-base font-semibold text-slate-950">解析任务</h2>
              <span className="text-xs text-slate-500">{jobs.length} items</span>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3 text-left">标题</th>
                    <th className="px-4 py-3 text-left">类型</th>
                    <th className="px-4 py-3 text-left">状态</th>
                    <th className="px-4 py-3 text-left">统计</th>
                    <th className="px-4 py-3 text-left">时间</th>
                    <th className="px-4 py-3 text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {jobs.slice(0, 24).map((job) => {
                    const result = jobResult(job)
                    return (
                      <tr key={job.job_id} className={selectedJobId === job.job_id ? 'bg-sky-50/60' : ''}>
                        <td className="max-w-[280px] truncate px-4 py-3 font-medium text-slate-900">{job.title || job.upload?.file_name || job.job_id}</td>
                        <td className="px-4 py-3 text-slate-600">{job.source_type}</td>
                        <td className="px-4 py-3"><Badge tone={statusTone(job.status)}>{job.status}</Badge></td>
                        <td className="px-4 py-3 text-slate-600">{String(result.pages ?? '-')} p / {String(result.chunks ?? '-')} chunks</td>
                        <td className="px-4 py-3 text-slate-500">{formatDateTime(job.created_at)}</td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex justify-end gap-2">
                            <Button onClick={() => loadReviewFromJob(job)} disabled={job.status !== 'completed'}>审核</Button>
                            {job.status === 'failed' && <Button onClick={() => showJobErrors(job)} disabled={busy}>错误</Button>}
                            <Button onClick={() => handleDeleteJob(job)} variant="danger" disabled={busy}>删除</Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <ReviewPanel review={review} busy={busy} onApprove={handleApprove} onReject={handleReject} onDelete={handleDeleteReview} />
        </div>
      </section>
    </div>
  )
}

function ReviewPanel({
  review,
  busy,
  onApprove,
  onReject,
  onDelete,
}: {
  review: ParsedDocumentReview | null
  busy: boolean
  onApprove: (mode: 'block' | 'replace' | 'new') => void
  onReject: (reason: string) => void
  onDelete: () => void
}) {
  const stats = parseJsonField<Record<string, unknown>>(review?.stats, {})
  const chunks = Array.isArray(review?.chunks) ? review.chunks : []
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState('内容无效，删除该解析结果')
  if (!review) {
    return (
      <div className="surface rounded-lg p-8 text-center">
        <h2 className="text-base font-semibold text-slate-950">审核面板</h2>
        <p className="mt-2 text-sm text-slate-500">完成解析后，在任务列表中打开审核内容。</p>
      </div>
    )
  }
  const approved = review.status === 'approved'
  return (
    <div className="surface rounded-lg">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-slate-950">{review.title}</h2>
            <Badge tone={statusTone(review.status)}>{review.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-500">{review.doc_type || 'document'} / {review.business_domain || 'general'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onApprove('block')} variant="success" disabled={busy || approved}>批准入库</Button>
          <Button onClick={() => onApprove('new')} disabled={busy || approved}>作为新文档</Button>
          <Button onClick={() => setRejectOpen((value) => !value)} variant="danger" disabled={busy || approved}>拒绝</Button>
          <Button onClick={onDelete} variant="danger" disabled={busy || approved}>删除草稿</Button>
        </div>
      </div>
      {rejectOpen && !approved && (
        <div className="border-b border-red-100 bg-red-50/70 p-5">
          <Field label="拒绝原因" htmlFor="reject-reason">
            <TextArea id="reject-reason" aria-labelledby="reject-reason-label" rows={3} value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} />
          </Field>
          <div className="mt-3 flex justify-end gap-2">
            <Button onClick={() => setRejectOpen(false)} disabled={busy}>取消</Button>
            <Button
              onClick={() => {
                onReject(rejectReason.trim() || '内容无效，删除该解析结果')
                setRejectOpen(false)
              }}
              variant="danger"
              disabled={busy}
            >
              确认拒绝
            </Button>
          </div>
        </div>
      )}
      <div className="grid gap-4 border-b border-slate-200 p-5 md:grid-cols-4">
        {([
          ['Pages', stats.pages ?? '-'],
          ['Chunks', chunks.length],
          ['Errors', stats.errors ?? 0],
          ['Hash', review.content_hash ? `${review.content_hash.slice(0, 10)}...` : '-'],
        ] as Array<[string, string | number]>).map(([label, value]) => (
          <div key={label} className="rounded-md border border-slate-200 bg-slate-50 p-3">
            <div className="text-xs text-slate-500">{label}</div>
            <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
          </div>
        ))}
      </div>
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="max-h-[680px] overflow-auto p-5">
          <pre className="whitespace-pre-wrap rounded-md bg-slate-950 p-4 text-xs leading-6 text-slate-100">{review.markdown_text || 'No markdown text'}</pre>
        </div>
        <div className="max-h-[680px] overflow-auto border-l border-slate-200 p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-950">Chunks</h3>
          <div className="space-y-3">
            {chunks.map((chunk) => (
              <div key={`${chunk.chunk_index}-${chunk.id}`} className="rounded-md border border-slate-200 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-mono text-xs text-slate-500">#{chunk.chunk_index}</span>
                  <Badge tone={statusTone(chunk.status)}>{chunk.status || 'draft'}</Badge>
                </div>
                <div className="text-xs text-slate-500">{chunk.section_path}</div>
                <p className="mt-2 line-clamp-5 whitespace-pre-wrap text-sm leading-6 text-slate-700">{chunk.content}</p>
              </div>
            ))}
            {chunks.length === 0 && <p className="text-sm text-slate-500">暂无分块草稿。</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
