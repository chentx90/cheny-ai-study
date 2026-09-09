# Frontend Module Framework

## 1. Module Boundary

The frontend only talks to the backend API. It does not access databases, object storage, vector indexes, or ingestion services directly.

```text
User
  ↓
Frontend
  ↓
Backend / RAG Gateway
```

## 2. Recommended Stack

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
Zod
Lucide icons
```

## 3. Directory Framework

```text
frontend/
  src/
    app/
      page.tsx
      retrieval/
        page.tsx
      knowledge/
        page.tsx
      evaluation/
        page.tsx

    components/
      layout/
        AppShell.tsx
        Sidebar.tsx
        TopBar.tsx

      retrieval/
        QueryPanel.tsx
        ModeSelector.tsx
        EvidenceList.tsx
        EvidenceCard.tsx
        AssetPreview.tsx
        RetrievalTrace.tsx
        RawJsonViewer.tsx

      knowledge/
        DocumentTable.tsx
        ChunkTable.tsx
        AssetTable.tsx
        DataAssetTable.tsx

      evaluation/
        EvaluationCaseTable.tsx
        EvaluationResultPanel.tsx
        FeedbackButtons.tsx

    lib/
      api.ts
      schemas.ts
      format.ts

    types/
      retrieval.ts
      document.ts
      evaluation.ts

  package.json
  README.md
```

## 4. Core Pages

### Retrieval Playground

Purpose:

```text
Submit query
Select mode
Toggle image/citation needs
Show evidence and trace
```

Route:

```text
/retrieval
```

### Knowledge Browser

Purpose:

```text
Inspect documents, chunks, assets, data assets
```

Route:

```text
/knowledge
```

### Evaluation Dashboard

Purpose:

```text
Run test cases
Show hit/miss
Collect manual feedback
```

Route:

```text
/evaluation
```

## 5. API Client Contract

`src/lib/api.ts` should provide:

```ts
export async function retrieve(payload: RetrieveRequest): Promise<RetrieveResponse>;

export async function listDocuments(): Promise<DocumentRecord[]>;

export async function listChunks(documentId?: string): Promise<ChunkRecord[]>;

export async function listDataAssets(): Promise<DataAssetRecord[]>;

export async function submitFeedback(payload: FeedbackRequest): Promise<void>;
```

## 6. Main Types

```ts
export type RetrieveRequest = {
  query: string;
  mode?: "fast" | "balanced" | "reliable" | "deep";
  constraints?: {
    business_domain?: string;
    need_image?: boolean;
    need_citation?: boolean;
  };
};

export type Evidence = {
  object_type: "chunk" | "data_asset";
  object_id: string;
  score: number;
  content: string;
  source?: Record<string, unknown>;
  assets?: Asset[];
};

export type RetrieveResponse = {
  query: string;
  intent?: string;
  confidence?: number;
  evidence: Evidence[];
  missing_info?: string[];
  retrieval_trace?: Record<string, unknown>;
};
```

## 7. First Files To Create

```text
src/app/page.tsx
src/app/retrieval/page.tsx
src/components/retrieval/QueryPanel.tsx
src/components/retrieval/EvidenceList.tsx
src/components/retrieval/RetrievalTrace.tsx
src/lib/api.ts
src/types/retrieval.ts
```

## 8. First Acceptance Test

```text
Open /retrieval
Input query
Click Retrieve
Show answer/evidence panel
Show trace panel
Show raw JSON
```