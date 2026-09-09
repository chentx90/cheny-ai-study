import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'RAG Console',
  description: 'File ingestion, review, embedding, and retrieval console',
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  )
}
