import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

const tones = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
  blue: 'bg-sky-50 text-sky-700 ring-sky-200',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
}

export function Badge({ children, tone = 'slate', className }: { children: ReactNode; tone?: keyof typeof tones; className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset', tones[tone], className)}>
      {children}
    </span>
  )
}
