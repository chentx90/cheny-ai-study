'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'

const nav = [
  { href: '/', label: '工作台', desc: '总览' },
  { href: '/ingestion', label: '导入审核', desc: '原始文件到向量' },
  { href: '/knowledge', label: '知识库', desc: '文档与分块' },
  { href: '/retrieval', label: '检索', desc: '召回测试' },
  { href: '/methods', label: '方法', desc: '策略配置' },
  { href: '/evaluation', label: '评估', desc: '质量看板' },
  { href: '/settings', label: '设置', desc: '运行参数' },
]

function isActive(pathname: string, href: string) {
  return href === '/' ? pathname === '/' : pathname.startsWith(href)
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname()

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-72 border-r border-slate-200 bg-white lg:flex lg:flex-col">
        <div className="border-b border-slate-200 px-6 py-5">
          <div className="text-base font-semibold text-slate-950">RAG Console</div>
          <div className="mt-1 text-xs text-slate-500">知识导入、审核与检索</div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-4">
          {nav.map((item) => {
            const active = isActive(pathname, item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'block rounded-md px-3 py-2.5 text-sm transition',
                  active
                    ? 'bg-sky-50 text-sky-900 ring-1 ring-inset ring-sky-100'
                    : 'text-slate-700 hover:bg-slate-100 hover:text-slate-950',
                )}
              >
                <div className="font-medium">{item.label}</div>
                <div className={cn('mt-0.5 text-xs', active ? 'text-sky-700' : 'text-slate-500')}>{item.desc}</div>
              </Link>
            )
          })}
        </nav>

        <div className="border-t border-slate-200 px-6 py-4">
          <div className="flex items-center gap-2 text-xs font-medium text-emerald-700">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            本地工作区
          </div>
          <div className="mt-2 font-mono text-[11px] text-slate-500">http://127.0.0.1:8000/api</div>
        </div>
      </aside>

      <div className="lg:pl-72">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur lg:hidden">
          <div className="px-4 py-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-slate-950">RAG Console</div>
                <div className="text-xs text-slate-500">导入、审核、检索</div>
              </div>
              <div className="flex items-center gap-2 text-xs text-emerald-700">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                Local
              </div>
            </div>
            <nav className="mt-3 flex gap-2 overflow-x-auto pb-1">
              {nav.map((item) => {
                const active = isActive(pathname, item.href)
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      'shrink-0 rounded-md px-3 py-1.5 text-xs font-medium',
                      active ? 'bg-slate-950 text-white' : 'bg-slate-100 text-slate-700',
                    )}
                  >
                    {item.label}
                  </Link>
                )
              })}
            </nav>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1760px] px-4 py-5 sm:px-6 lg:px-8 lg:py-6">{children}</main>
      </div>
    </div>
  )
}
