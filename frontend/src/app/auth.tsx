import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'

import { api, setCsrf, setUnauthorizedHandler } from '../lib/api'
import type { Me } from '../lib/types'

interface AuthValue {
  me: Me | null
  isLoading: boolean
  can: (permission: string) => boolean
  login: (email: string, password: string) => Promise<void>
  signup: (input: { email: string; password: string; name: string; workspace_name: string }) => Promise<void>
  acceptInvite: (input: { token: string; name: string; password: string }) => Promise<void>
  logout: () => Promise<void>
  switchWorkspace: (workspaceId: string) => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const meQuery = useQuery({
    queryKey: ['me'],
    queryFn: async (): Promise<Me | null> => {
      try {
        const me = await api<Me>('/api/auth/me', { skipUnauthorized: true })
        setCsrf(me.csrf_token)
        return me
      } catch (e) {
        if ((e as { status?: number }).status === 401) return null
        throw e
      }
    },
    staleTime: 60_000,
  })
  const me = meQuery.data ?? null

  const reset = useCallback(() => {
    setCsrf('')
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })
    queryClient.setQueryData(['me'], null)
  }, [queryClient])

  useEffect(() => {
    setUnauthorizedHandler(reset)
    return () => setUnauthorizedHandler(null)
  }, [reset])

  const refreshMe = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ['me'] })
    await queryClient.refetchQueries({ queryKey: ['me'] })
  }, [queryClient])

  const value = useMemo<AuthValue>(
    () => ({
      me,
      isLoading: meQuery.isPending,
      can: (permission) => !!me?.permissions.includes(permission),
      login: async (email, password) => {
        const res = await api<{ csrf_token: string }>('/api/auth/login', {
          method: 'POST',
          body: { email, password },
          skipUnauthorized: true,
        })
        setCsrf(res.csrf_token)
        queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })
        await refreshMe()
      },
      signup: async (input) => {
        const res = await api<{ csrf_token: string }>('/api/auth/signup', {
          method: 'POST',
          body: input,
          skipUnauthorized: true,
        })
        setCsrf(res.csrf_token)
        await refreshMe()
      },
      acceptInvite: async (input) => {
        const res = await api<{ csrf_token: string }>('/api/auth/accept-invite', {
          method: 'POST',
          body: input,
          skipUnauthorized: true,
        })
        setCsrf(res.csrf_token)
        await refreshMe()
      },
      logout: async () => {
        await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
        reset()
      },
      switchWorkspace: async (workspaceId) => {
        await api('/api/workspaces/switch', { method: 'POST', body: { workspace_id: workspaceId } })
        queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })
        await refreshMe()
      },
    }),
    [me, meQuery.isPending, queryClient, refreshMe, reset],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
