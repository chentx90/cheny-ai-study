import Link from 'next/link'
import { AppShell } from '@/shared/layout/AppShell'

const primaryActions = [
  {
    href: '/ingestion',
    title: '导入审核',
    value: '原始文件 -> 草稿 -> 入库',
    text: '上传文件或导入目录，生成可审阅分块，批准后进入知识库和向量任务。',
  },
  {
    href: '/knowledge',
    title: '知识库',
    value: '文档 / 分块 / 来源',
    text: '查看已批准文档、chunk 内容、来源文件资产和业务域。',
  },
  {
    href: '/retrieval',
    title: '检索调试',
    value: '证据 / 分数 / 轨迹',
    text: '验证问题召回、证据片段、资源引用和执行链路。',
  },
  {
    href: '/evaluation',
    title: '质量评估',
    value: '命中率 / 延迟 / 样本',
    text: '跑批检查召回质量，对比方法效果并沉淀错误样本。',
  },
]

const pipeline = [
  ['01', '保存原始文件', '对象存储保留源文件，支持回溯原文。'],
  ['02', '解析生成草稿', '抽取 Markdown、表格、页码和 chunk 草稿。'],
  ['03', '人工审阅批准', '在入库前检查标题、全文、分块和统计。'],
  ['04', '写入知识库', '批准后生成文档、分块和 embedding 任务。'],
]

export default function Home() {
  return (
    <AppShell>
      <div className="space-y-5">
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="surface rounded-lg p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-sky-700">RAG Modular System</p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">文档导入、审核与检索工作台</h1>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                  当前流程围绕可追溯的原始文件、可审阅的解析草稿、可批准的知识入库和可验证的检索结果组织。
                </p>
              </div>
              <Link
                href="/ingestion"
                className="inline-flex h-10 items-center justify-center rounded-md bg-slate-950 px-4 text-sm font-medium text-white transition hover:bg-slate-800"
              >
                开始导入
              </Link>
            </div>
          </div>

          <div className="surface rounded-lg p-5">
            <div className="text-sm font-semibold text-slate-950">运行状态</div>
            <div className="mt-4 space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">后端 API</span>
                <span className="font-medium text-emerald-700">127.0.0.1:8000</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">对象存储</span>
                <span className="font-medium text-slate-900">MinIO / Local</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">数据库</span>
                <span className="font-medium text-slate-900">PostgreSQL</span>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {primaryActions.map((card) => (
            <Link key={card.href} href={card.href} className="surface rounded-lg p-5 transition hover:-translate-y-0.5 hover:shadow-md">
              <div className="text-sm font-medium text-slate-500">{card.title}</div>
              <div className="mt-2 text-base font-semibold text-slate-950">{card.value}</div>
              <p className="mt-3 text-sm leading-6 text-slate-600">{card.text}</p>
            </Link>
          ))}
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="surface rounded-lg p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-950">处理链路</h2>
              <span className="text-xs text-slate-500">Review before embedding</span>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              {pipeline.map(([step, title, text]) => (
                <div key={step} className="rounded-md border border-slate-200 bg-slate-50 p-4">
                  <div className="font-mono text-xs font-semibold text-sky-700">{step}</div>
                  <div className="mt-2 text-sm font-semibold text-slate-950">{title}</div>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{text}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="surface rounded-lg p-5">
            <h2 className="text-base font-semibold text-slate-950">本地启动</h2>
            <div className="mt-4 space-y-3 text-sm text-slate-600">
              <div>
                <div className="mb-1 text-xs font-medium text-slate-500">Backend</div>
                <code className="block rounded-md bg-slate-950 px-3 py-2 text-xs text-slate-100">uvicorn backend.app.main:app --reload</code>
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-slate-500">Frontend</div>
                <code className="block rounded-md bg-slate-950 px-3 py-2 text-xs text-slate-100">npm run dev</code>
              </div>
              <p>MinIO 未启动时会降级到本地对象存储。</p>
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  )
}
