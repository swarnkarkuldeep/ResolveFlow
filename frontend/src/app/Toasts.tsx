import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

type Tone = 'info' | 'error'
interface Toast {
  id: number
  message: string
  tone: Tone
}

const ToastContext = createContext<(message: string, tone?: Tone) => void>(() => undefined)

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)

  const push = useCallback((message: string, tone: Tone = 'info') => {
    const id = nextId.current++
    setToasts((t) => [...t, { id, message, tone }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 6000 : 3500)
  }, [])

  const value = useMemo(() => push, [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-20 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2 md:bottom-6">
        {toasts.map((t) => (
          <p
            key={t.id}
            role={t.tone === 'error' ? 'alert' : 'status'}
            className={`toast-in pointer-events-auto max-w-[90vw] rounded-control border px-3.5 py-2 text-[14px] ${
              t.tone === 'error' ? 'border-danger bg-paper text-danger' : 'border-line bg-ink text-paper'
            }`}
          >
            {t.message}
          </p>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
