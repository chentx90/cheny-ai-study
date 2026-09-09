'use client'

import { useEffect, useState } from 'react'
import { deleteDocument, listChunks, listDataAssets, listDocuments } from '@/lib/knowledgeApi'
import type { KnowledgeChunk, KnowledgeDataAsset, KnowledgeDoc } from '@/types/knowledge'
import { Badge } from '@/shared/ui/Badge'
import { Button } from '@/shared/ui/Button'
import { Field, TextInput } from '@/shared/ui/Field'

export function KnowledgeWorkspace() {
  const [documents, setDocuments] = useState<KnowledgeDoc[]>([])
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([])
  const [dataAssets, setDataAssets] = useState<KnowledgeDataAsset[]>([])
  const [selectedDoc, setSelectedDoc] = useState<KnowledgeDoc | null>(null)
  const [keyword, setKeyword] = useState('')
  const [businessDomain, setBusinessDomain] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function refresh() {
    setLoading(true)
    setError('')
    try {
      const [docs, assets] = await Promise.all([
        listDocuments({ keyword, business_domain: businessDomain }),
        listDataAssets({ keyword, business_domain: businessDomain }),
      ])
      setDocuments(docs.documents)
      setDataAssets(assets.data_assets)
      if (selectedDoc && !docs.documents.some((doc) => doc.id === selectedDoc.id)) {
        setSelectedDoc(null)
        setChunks([])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载知识库失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function openDocument(doc: KnowledgeDoc) {
    setSelectedDoc(doc)
    setChunks([])
    try {
      const data = await listChunks(doc.id)
      setChunks(data.chunks)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载分块失败')
    }
  }

  async function archiveDocument(doc: KnowledgeDoc) {
    if (!window.confirm(`归档文档：${doc.title}`)) return
    await deleteDocument(doc.id)
    await refresh()
  }

  return (
    <div className="space-y-5">
      <div className="surface rounded-lg p-4">
        <div className="grid gap-3 md:grid-cols-[1fr_220px_auto]">
          <Field label="关键词">
            <TextInput value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="标题、来源、描述" />
          </Field>
          <Field label="业务域">
            <TextInput value={businessDomain} onChange={(event) => setBusinessDomain(event.target.value)} placeholder="general / electronics" />
          </Field>
          <div className="flex items-end">
            <Button onClick={refresh} variant="primary" disabled={loading} className="w-full">查询</Button>
          </div>
        </div>
      </div>

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="surface rounded-lg">
          <div className="flex items-center justify-between border-b border-slate-200 p-4">
            <h2 className="text-base font-semibold text-slate-950">文档</h2>
            <span className="text-xs text-slate-500">{documents.length} items</span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">标题</th>
                  <th className="px-4 py-3 text-left">类型</th>
                  <th className="px-4 py-3 text-left">业务域</th>
                  <th className="px-4 py-3 text-left">状态</th>
                  <th className="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {documents.map((doc) => (
                  <tr key={doc.id} className={selectedDoc?.id === doc.id ? 'bg-sky-50/70' : ''}>
                    <td className="max-w-[360px] truncate px-4 py-3 font-medium text-slate-900">{doc.title}</td>
                    <td className="px-4 py-3 text-slate-600">{doc.doc_type}</td>
                    <td className="px-4 py-3 text-slate-600">{doc.business_domain || '-'}</td>
                    <td className="px-4 py-3"><Badge tone="green">{doc.status || 'active'}</Badge></td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex gap-2">
                        <Button onClick={() => openDocument(doc)}>查看</Button>
                        <Button onClick={() => archiveDocument(doc)} variant="danger">归档</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-5">
          <div className="surface rounded-lg">
            <div className="border-b border-slate-200 p-4">
              <h2 className="text-base font-semibold text-slate-950">分块预览</h2>
              <p className="mt-1 text-xs text-slate-500">{selectedDoc ? selectedDoc.title : '选择文档查看 chunks'}</p>
            </div>
            <div className="max-h-[520px] space-y-3 overflow-auto p-4">
              {chunks.map((chunk) => (
                <div key={chunk.id} className="rounded-md border border-slate-200 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-mono text-xs text-slate-500">#{chunk.chunk_index}</span>
                    <span className="text-xs text-slate-500">{chunk.section_path}</span>
                  </div>
                  <p className="line-clamp-6 whitespace-pre-wrap text-sm leading-6 text-slate-700">{chunk.content}</p>
                </div>
              ))}
              {selectedDoc && chunks.length === 0 && <p className="text-sm text-slate-500">暂无分块。</p>}
            </div>
          </div>

          <div className="surface rounded-lg">
            <div className="border-b border-slate-200 p-4">
              <h2 className="text-base font-semibold text-slate-950">数据资产</h2>
            </div>
            <div className="max-h-[300px] overflow-auto p-4">
              {dataAssets.map((asset) => (
                <div key={asset.id} className="mb-3 rounded-md border border-slate-200 p-3">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-slate-900">{asset.name}</div>
                    <Badge>{asset.asset_type}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-600">{asset.description || '-'}</p>
                </div>
              ))}
              {dataAssets.length === 0 && <p className="text-sm text-slate-500">暂无数据资产。</p>}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
