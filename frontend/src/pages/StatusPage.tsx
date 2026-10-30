import { useQuery } from '@tanstack/react-query'

import { fetchSystem } from '../api/health'

export function StatusPage() {
  const { data, isError, isPending } = useQuery({
    queryKey: ['system-health'],
    queryFn: fetchSystem,
    refetchInterval: 10_000,
  })

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-xl font-semibold">ResolveFlow</h1>
      <p className="mb-6 text-sm text-neutral-500">System status</p>
      {isPending && <p>Checking…</p>}
      {isError && <p role="alert">Unable to reach the API.</p>}
      {data && (
        <ul className="divide-y divide-neutral-200 rounded-md border border-neutral-200">
          {data.checks.map((c) => (
            <li key={c.name} className="flex items-center justify-between px-4 py-3">
              <span className="flex items-center gap-2">
                <span
                  aria-label={c.ok ? 'ok' : 'not ok'}
                  className={`h-2 w-2 rounded-full ${c.ok ? 'bg-green-500' : 'bg-red-500'}`}
                />
                <span>{c.name}</span>
              </span>
              <span className="text-sm text-neutral-500">{c.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
