import type { ReactNode } from 'react'

export function AuthLayout({ title, lead, children, footer }: { title: string; lead: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-fog px-4 py-12">
      <div className="w-full max-w-[400px]">
        <p className="mb-8 flex items-center gap-2 font-serif text-[22px] font-medium tracking-tight">
          <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-[3px] bg-accent" />
          ResolveFlow
        </p>
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight">{title}</h1>
        <p className="mb-6 mt-1.5 text-[15px] text-slate">{lead}</p>
        {children}
        {footer && <p className="mt-6 text-[14px] text-slate">{footer}</p>}
      </div>
    </div>
  )
}
