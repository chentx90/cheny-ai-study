export interface KnowledgeDoc {
  id: string
  title: string
  doc_type: string
  source_uri?: string
  business_domain: string
  version: string
  status: string
  chunk_count: number
}

export interface KnowledgeChunk {
  id: string
  chunk_index: number
  section_path: string
  title_context: string
  content: string
  summary: string
  preset_questions: string[]
}

export interface KnowledgeDataAsset {
  id: string
  asset_type: string
  name: string
  description: string
  business_domain: string
  formula: string
}
