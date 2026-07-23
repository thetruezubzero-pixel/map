import type { ReactNode } from 'react'
import { DashboardNav } from '@/components/DashboardNav'

export function PageShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col overflow-y-auto bg-background text-text">
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 sm:gap-4 sm:px-4 sm:py-3">
        <h1 className="shrink-0 whitespace-nowrap text-base font-semibold text-text sm:text-lg">Aether Sovereign OS</h1>
        <DashboardNav />
      </header>
      <main className="flex-1 overflow-y-auto px-3 py-3 sm:p-6">
        <div className="mx-auto max-w-4xl">
          <h2 className="mb-3 text-sm font-semibold text-text sm:mb-4 sm:text-base">{title}</h2>
          {children}
        </div>
      </main>
    </div>
  )
}
