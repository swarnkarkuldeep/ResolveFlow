import type { components } from './schema'

export type SystemResponse = components['schemas']['SystemOut']

export async function fetchSystem(): Promise<SystemResponse> {
  const res = await fetch('/api/health/system')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
