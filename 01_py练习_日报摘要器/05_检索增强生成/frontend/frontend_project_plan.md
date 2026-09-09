# Frontend Project Plan

## 1. Module Goal

The frontend is the visual demo layer of the RAG system. It helps users test retrieval, inspect evidence, view retrieval traces, and understand how Agent routing chooses different retrieval strategies.

This frontend is an operational interface for learning, debugging, and demonstrating a modular RAG system.

## 2. Core Screens

### 2.1 Retrieval Playground

Purpose:

```text
Input question
Select retrieval mode
Send request to backend
Display answer, evidence, assets, trace
```

Main controls:

```text
Query input
Mode selector: fast / balanced / reliable / deep
Business domain selector
Need image toggle
Need citation toggle
Retrieve button
```

Output panels:

```text
Final answer
Evidence list
Source metadata
Image assets
Retrieval trace
Raw JSON response
```

### 2.2 Knowledge Browser

Purpose:

```text
Browse documents, chunks, assets, and data assets
Check whether ingestion results are usable
```

Views:

```text
Documents
Chunks
Assets
Data Assets
```

### 2.3 Retrieval Trace Viewer

Purpose:

```text
Show how a query becomes a retrieval plan
Show which strategies and backends were used
```

Trace content:

```text
Intent
Selected strategies
Selected backend capabilities
Latency
Returned chunks
Scores
```

### 2.4 Evaluation Dashboard

Purpose:

```text
Manually test retrieval quality
Compare expected evidence with actual evidence
```

Metrics:

```text
Hit / Miss
Top-k result quality
Latency
Manual feedback
```

## 3. Suggested Tech Stack

```text
React / Next.js
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
Zod
Lucide icons
```

## 4. API Dependencies

Frontend calls backend only.

```text
POST /retrieve
GET  /documents
GET  /documents/{id}/chunks
GET  /assets
GET  /data-assets
GET  /evaluation/runs
POST /evaluation/feedback
```

The frontend should not directly access PostgreSQL, vector indexes, or object storage.

## 5. Suggested Directory Structure

```text
frontend/
  src/
    app/
    components/
      retrieval/
      knowledge/
      trace/
      evaluation/
      layout/
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

## 6. First Vibe Coding Tasks

1. Create retrieval playground page.
2. Add query input and mode selector.
3. Call mock `/retrieve` endpoint.
4. Render evidence cards.
5. Render retrieval trace JSON.
6. Add knowledge browser table.
7. Add simple evaluation feedback buttons.

## 7. Acceptance Criteria

```text
User can submit a query
Frontend can display answer and evidence
Frontend can show image URLs when available
Frontend can show retrieval trace
Frontend can inspect raw JSON
Frontend can run without knowing database details
```

## 8. Demo Scenario

Question:

```text
液压泵压力不足应该怎么排查？
```

Expected UI result:

```text
Answer panel shows suggested checks
Evidence panel shows related chunk
Asset panel shows image URL
Trace panel shows selected strategies and backend capabilities
```