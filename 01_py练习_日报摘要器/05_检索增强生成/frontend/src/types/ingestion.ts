export type IngestionJobStatus =
  | 'pending'
  | 'uploading'
  | 'parsing'
  | 'chunking'
  | 'embedding'
  | 'writing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type IngestionSourceType = 'pdf' | 'excel' | 'markdown' | 'json' | 'csv' | 'txt' | 'docx' | 'pptx'

export interface FileAsset {
  id: string
  original_filename: string
  relative_path?: string
  bucket: string
  object_key: string
  storage_backend: string
  file_ext?: string
  mime_type?: string
  file_size?: number
  content_hash?: string
  business_domain?: string
  source_batch_id?: string | null
  status: string
  created_at: string
}

export interface IngestionUpload {
  upload_id: string
  file_asset_id?: string
  file_name: string
  file_type: string
  file_size: number
  storage_uri: string
  status: string
  created_at: string
  file_asset?: FileAsset
}

export interface IngestionJob {
  job_id: string
  upload_id?: string
  upload?: IngestionUpload
  source_type: IngestionSourceType
  title?: string
  business_domain?: string
  doc_type?: string
  version?: string
  mode?: 'preview' | 'ingest'
  status: IngestionJobStatus
  stage?: string
  progress: number
  options?: Record<string, unknown> | string
  preview_uri?: string
  result?: Record<string, unknown> | string
  error_count: number
  created_at: string
  started_at?: string
  finished_at?: string
}

export interface IngestionJobError {
  id?: string
  job_id?: string
  stage: string
  object_ref?: string
  message: string
  suggestion?: string
  raw_error?: string
  created_at?: string
}

export interface ChunkDraft {
  id?: string
  parsed_document_id?: string
  chunk_index: number
  section_path: string
  title_context: string
  content: string
  summary?: string
  preset_questions?: string[] | string
  physical_context?: Record<string, unknown> | string | null
  status?: string
  created_at?: string
}

export interface DataAssetPreview {
  asset_type: string
  name: string
  description?: string
  business_domain?: string
  parent_name?: string
  synonyms?: string[]
  formula?: string
  related_table?: string
  related_columns?: string[]
  example_values?: Record<string, unknown>
}

export interface SheetPreview {
  sheet_name: string
  rows: number
  columns?: number
  tables?: number
  data_assets?: Record<string, unknown>[]
}

export interface IngestionPreview {
  job_id: string
  document?: {
    title: string
    doc_type: string
    business_domain: string
    source_uri?: string
    content_hash?: string
  }
  pages: { page_number: number; text: string; metadata?: Record<string, unknown> }[]
  chunks: ChunkDraft[]
  data_assets: DataAssetPreview[]
  sheets: SheetPreview[]
  errors: IngestionJobError[]
  stats: {
    pages?: number
    chunks?: number
    data_assets?: number
    sheets?: number
    errors?: number
  }
}

export interface ParsedDocumentReview {
  id: string
  file_asset_id?: string
  parse_job_id?: string
  title: string
  doc_type?: string
  business_domain?: string
  content_hash?: string
  markdown_text?: string
  stats?: Record<string, unknown> | string
  status: 'draft' | 'approved' | 'rejected' | string
  review_notes?: string
  kb_document_id?: string
  created_at: string
  approved_at?: string
  chunks?: ChunkDraft[]
}

export interface ApprovalResult {
  embedding_job_id: string
  document_id: string
  chunks: number
}
