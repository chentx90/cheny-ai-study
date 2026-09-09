export type RetrievalMode = 'fast' | 'balanced' | 'reliable' | 'deep'

export interface RetrieveRequest {
  query: string
  method?: string
  mode?: RetrievalMode
  constraints?: {
    business_domain?: string
    need_image?: boolean
    need_citation?: boolean
    [key: string]: unknown
  }
}

export interface AssetItem {
  asset_id: string
  asset_type: string
  asset_url?: string
  caption?: string | null
  ocr_text?: string | null
  description?: string | null
  physical_context?: Record<string, unknown>
}

export interface EvidenceItem {
  chunk_id: string
  document_id: string
  section_path?: string
  title_context?: string
  content: string
  score: number
  physical_context?: Record<string, unknown>
  assets?: AssetItem[]
}

export interface DataAssetItem {
  asset_id: string
  asset_type: 'table' | 'column' | 'metric' | 'case' | 'tool' | string
  name: string
  description?: string
  business_domain?: string
  parent_name?: string
  synonyms?: string[]
  formula?: string
  related_table?: string
  related_columns?: string[]
  score?: number
}

export interface TraceStep {
  name: string
  operator: string
  backend: string
  status: 'ok' | 'error' | 'skipped'
  latency_ms: number
  input_count?: number
  output_count?: number
  error?: string | null
}

export interface RetrievalTrace {
  latency_ms: number
  steps?: TraceStep[]
  strategies?: string[]
  backends?: string[]
}

export interface KnowledgePackage {
  query: string
  method?: string
  intent?: string
  confidence?: number
  evidence: EvidenceItem[]
  assets?: AssetItem[]
  data_assets?: DataAssetItem[]
  missing_info?: string[]
  retrieval_trace?: RetrievalTrace
}

export interface CapabilityRegistry {
  backend_id: string
  capabilities: string[]
}

export interface RetrievalMethodSummary {
  method_id: string
  description?: string
  version?: string
  enabled?: boolean
}

export interface MethodStep {
  name: string
  operator: string
  backend: string
  params?: Record<string, unknown>
}

export interface RetrievalMethodDetail extends RetrievalMethodSummary {
  steps: MethodStep[]
}

export interface RetrievePlanResponse {
  query: string
  resolved_method: string
  description?: string
  steps: MethodStep[]
}