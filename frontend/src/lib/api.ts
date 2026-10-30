export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

let csrfToken = ''
let onUnauthorized: (() => void) | null = null

export function setCsrf(token: string) {
  csrfToken = token
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function messageFrom(status: number, body: unknown): { code: string; message: string } {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = detail as { code?: string; message?: string }
    if (d.message) return { code: d.code ?? 'error', message: d.message }
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return { code: 'invalid', message: 'Some fields need attention. Check what you entered and try again.' }
  }
  if (status >= 500) return { code: 'server_error', message: 'Something went wrong on our side. Try again in a moment.' }
  return { code: 'error', message: 'The request could not be completed.' }
}

type Options = { method?: string; body?: unknown; skipUnauthorized?: boolean }

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? (options.body !== undefined ? 'POST' : 'GET')
  const headers: Record<string, string> = {}
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (UNSAFE.has(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network', 'Unable to reach ResolveFlow. Check your connection and try again.')
  }
  const text = await res.text()
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = null
    }
  }
  if (!res.ok) {
    if (res.status === 401 && !options.skipUnauthorized) onUnauthorized?.()
    const { code, message } = messageFrom(res.status, parsed)
    throw new ApiError(res.status, code, message)
  }
  return parsed as T
}
