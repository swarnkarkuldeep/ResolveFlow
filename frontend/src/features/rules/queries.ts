import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { api } from '../../lib/api'
import type { Member, RuleDetail, RuleSummary, Team } from '../../lib/types'
import type { Names } from './vocab'

export function useRules() {
  return useQuery({ queryKey: ['rules'], queryFn: () => api<RuleSummary[]>('/api/rules') })
}

export function useRule(id: string | undefined) {
  return useQuery({
    queryKey: ['rule', id],
    enabled: !!id,
    queryFn: () => api<RuleDetail>(`/api/rules/${id}`),
  })
}

export function useTeamsList() {
  return useQuery({ queryKey: ['teams'], queryFn: () => api<Team[]>('/api/teams') })
}

export function usePeople() {
  return useQuery({ queryKey: ['members'], queryFn: () => api<Member[]>('/api/members') })
}

export function useNames(): { names: Names; people: Member[]; teams: Team[] } {
  const peopleQuery = usePeople()
  const teamsQuery = useTeamsList()
  const people = useMemo(() => peopleQuery.data ?? [], [peopleQuery.data])
  const teams = useMemo(() => teamsQuery.data ?? [], [teamsQuery.data])
  const names = useMemo<Names>(
    () => ({
      users: Object.fromEntries(people.map((p) => [p.user_id, p.name])),
      teams: Object.fromEntries(teams.map((t) => [t.id, t.name])),
    }),
    [people, teams],
  )
  return { names, people, teams }
}
