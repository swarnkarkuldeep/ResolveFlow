import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import type { SearchHit } from '../../lib/types'
import { PriorityMark, Spinner, StatusMark, TextInput } from '../../ui'

const ENTITIES: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'" }
const decode = (s: string) => s.replace(/&(?:amp|lt|gt|quot|#x27);/g, (m) => ENTITIES[m])

/** Renders the server's escaped snippet, turning only its <mark> pairs into highlights. */
export function Snippet({ html }: { html: string }) {
  const parts = html.split(/(<mark>.*?<\/mark>)/g).filter(Boolean)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('<mark>') ? (
          <mark key={i} className="rounded-sm bg-accent/20 px-0.5 text-ink">
            {decode(p.slice(6, -7))}
          </mark>
        ) : (
          <span key={i}>{decode(p)}</span>
        ),
      )}
    </>
  )
}

function useDebounced(value: string, ms: number) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim(), 250)

  useEffect(() => {
    const next = new URLSearchParams(params)
    if (q) next.set('q', q)
    else next.delete('q')
    if (next.toString() !== params.toString()) setParams(next, { replace: true })
  }, [q, params, setParams])

  const results = useQuery({
    queryKey: ['search', q],
    enabled: q.length > 0,
    queryFn: () => api<{ items: SearchHit[] }>(`/api/search?q=${encodeURIComponent(q)}`),
  })
  const items = results.data?.items ?? []

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[760px] px-6 py-8">
        <h1 className="text-[24px] font-semibold tracking-tight">Search</h1>
        <p className="mb-4 mt-1 text-[14px] text-slate">Find tickets by what the customer wrote or by the subject.</p>
        <label htmlFor="search-q" className="sr-only">
          Search tickets
        </label>
        <TextInput
          id="search-q"
          type="search"
          autoFocus
          placeholder="Search subjects and messages"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="mt-6" aria-live="polite">
          {q === '' && <p className="text-[14px] text-slate">Type a word or phrase. Use quotes to match an exact phrase.</p>}
          {q !== '' && results.isFetching && items.length === 0 && <Spinner label="Searching" />}
          {results.isError && <p className="text-danger">{results.error.message}</p>}
          {results.isSuccess && items.length === 0 && (
            <div>
              <p className="font-medium">No tickets match “{q}”</p>
              <p className="mt-1 text-[14px] text-slate">Try fewer or different words.</p>
            </div>
          )}
          {items.length > 0 && (
            <ul aria-label="Search results">
              {items.map((t) => (
                <li key={t.id} className="border-b border-line/70 py-3.5">
                  <Link to={`/inbox/${t.id}`} className="block hover:text-accent">
                    <span className="flex items-center gap-2 text-[15px] font-medium">
                      <StatusMark status={t.status} label={false} />
                      <span className="truncate">{t.subject}</span>
                      <span className="shrink-0 text-[13px] font-normal text-slate">#{t.number}</span>
                    </span>
                  </Link>
                  <p className="mt-1 max-w-[68ch] font-serif text-[15px] leading-relaxed text-ink/80">
                    <Snippet html={t.snippet_html} />
                  </p>
                  <p className="mt-1 flex items-center gap-2 text-[13px] text-slate">
                    <PriorityMark priority={t.priority} />
                    <span>{t.requester.name || t.requester.email}</span>
                    <span>· {t.match === 'subject' ? 'Matched the subject' : 'Matched a message'}</span>
                    <span>· {relativeTime(t.last_activity_at)}</span>
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
