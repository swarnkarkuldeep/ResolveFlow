import { useEffect, useId, useRef } from 'react'
import type { ButtonHTMLAttributes, ComponentProps, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react'
import { ArrowUp, ChevronsUp, Minus } from 'lucide-react'

import { initials } from '../lib/format'
import { PRIORITY_LABEL, STATUS_LABEL } from '../lib/types'
import type { Priority, Status } from '../lib/types'

/* ---------- Buttons ---------- */

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent text-accent-ink hover:brightness-110 border border-transparent',
  secondary: 'bg-paper text-ink border border-line hover:bg-wash',
  ghost: 'bg-transparent text-slate hover:bg-wash hover:text-ink border border-transparent',
  danger: 'bg-transparent text-danger border border-line hover:bg-wash',
}

export function Button({
  variant = 'secondary',
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...rest}
      className={`inline-flex h-9 items-center justify-center gap-2 rounded-control px-3.5 text-[14px] font-medium transition-colors disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
    />
  )
}

/* ---------- Form controls ---------- */

const CONTROL =
  'w-full rounded-control border border-line bg-paper px-3 text-[15px] text-ink placeholder:text-slate/70 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60'

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string
  hint?: string
  error?: string | null
  children: ReactNode
  htmlFor: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[13px] font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-[13px] text-slate">{hint}</p>}
      {error && <p className="text-[13px] text-danger">{error}</p>}
    </div>
  )
}

export function TextInput({ className = '', ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={`${CONTROL} h-10 ${className}`} />
}

export function TextArea({ className = '', ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...rest} className={`${CONTROL} py-2.5 leading-relaxed ${className}`} />
}

export function Select({ className = '', ...rest }: ComponentProps<'select'>) {
  return <select {...rest} className={`${CONTROL} h-9 pr-8 ${className}`} />
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="rounded-control border border-line bg-wash px-3 py-2 text-[14px] text-danger">
      {message}
    </p>
  )
}

/* ---------- People and markers ---------- */

export function Avatar({ name, size = 28 }: { name: string | null | undefined; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-wash text-[11px] font-semibold text-slate"
      style={{ width: size, height: size }}
    >
      {initials(name)}
    </span>
  )
}

const STATUS_COLOR: Record<Status, string> = {
  new: 'var(--st-new)',
  open: 'var(--st-open)',
  pending: 'var(--st-pending)',
  resolved: 'var(--st-resolved)',
  closed: 'var(--st-closed)',
}

export function StatusMark({ status, label = true }: { status: Status; label?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-slate">
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 rounded-full"
        style={{
          background: status === 'closed' ? 'transparent' : STATUS_COLOR[status],
          boxShadow: status === 'closed' ? `inset 0 0 0 1.5px ${STATUS_COLOR[status]}` : undefined,
        }}
      />
      {label ? STATUS_LABEL[status] : <span className="sr-only">{STATUS_LABEL[status]}</span>}
    </span>
  )
}

export function PriorityMark({ priority }: { priority: Priority }) {
  if (priority === 'normal') return null
  const Icon = priority === 'urgent' ? ChevronsUp : priority === 'high' ? ArrowUp : Minus
  const color = priority === 'urgent' ? 'var(--pr-urgent)' : priority === 'high' ? 'var(--pr-high)' : 'var(--slate)'
  return (
    <span title={`${PRIORITY_LABEL[priority]} priority`} className="inline-flex items-center" style={{ color }}>
      <Icon size={15} strokeWidth={2.25} aria-hidden="true" />
      <span className="sr-only">{PRIORITY_LABEL[priority]} priority</span>
    </span>
  )
}

/* ---------- Dialog ---------- */

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

export function Dialog({
  title,
  onClose,
  children,
  width = 480,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  width?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const node = ref.current
    const first = node?.querySelector<HTMLElement>('[data-autofocus]') ?? node?.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
      if (e.key === 'Tab' && node) {
        const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
        if (items.length === 0) return
        const first = items[0]
        const last = items[items.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      previous?.focus()
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh]" onMouseDown={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(e) => e.stopPropagation()}
        className="pane-in w-full rounded-panel border border-line bg-paper p-6"
        style={{ maxWidth: width }}
      >
        <h2 id={titleId} className="mb-4 text-[18px] font-semibold tracking-tight">
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <p role="status" className="px-4 py-6 text-[14px] text-slate">
      {label}…
    </p>
  )
}
