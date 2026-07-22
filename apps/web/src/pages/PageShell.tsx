import type { ReactNode } from 'react'
import { DashboardNav } from '@/components/DashboardNav'

export function PageShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col overflow-y-auto bg-background text-text">
      <header className="flex items-center gap-4 border-b border-border px-4 py-3">
        <h1 className="whitespace-nowrap text-lg font-semibold text-text">Aether Sovereign OS</h1>
        <DashboardNav />
      </header>
      <main className="flex-1 p-6">
        <h2 className="mb-4 text-base font-semibold text-text">{title}</h2>
        {children}
      </main>
    </div>
  )
}
