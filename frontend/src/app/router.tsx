import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

import { AcceptInvitePage } from '../features/auth/AcceptInvitePage'
import { LoginPage } from '../features/auth/LoginPage'
import { SignupPage } from '../features/auth/SignupPage'
import { AuditPage } from '../features/audit/AuditPage'
import { AnalyticsPage } from '../features/analytics/AnalyticsPage'
import { CustomerPage } from '../features/customers/CustomerPage'
import { NotificationsPage } from '../features/notifications/NotificationsPage'
import { SearchPage } from '../features/search/SearchPage'
import { ChannelsPage } from '../features/channels/ChannelsPage'
import { InboxPage } from '../features/inbox/InboxPage'
import { PeoplePage } from '../features/people/PeoplePage'
import { RuleEditorPage } from '../features/rules/RuleEditorPage'
import { RulesPage } from '../features/rules/RulesPage'
import { PublicFormPage } from '../features/publicform/PublicFormPage'
import { SlaSettingsPage } from '../features/sla/SlaSettingsPage'
import { useAuth } from './auth'
import { Shell } from './Shell'

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) return <p role="status" className="p-6 text-slate">Loading…</p>
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <>{children}</>
}

function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth()
  if (!can(permission)) return <Navigate to="/inbox" replace />
  return <>{children}</>
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/accept-invite" element={<AcceptInvitePage />} />
      <Route path="/form/:slug" element={<PublicFormPage />} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/inbox/:ticketId" element={<InboxPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/customers/:id" element={<CustomerPage />} />
        <Route path="/analytics" element={<RequirePermission permission="analytics:read"><AnalyticsPage /></RequirePermission>} />
        <Route path="/people" element={<RequirePermission permission="user:read"><PeoplePage /></RequirePermission>} />
        <Route path="/channels" element={<RequirePermission permission="settings:read"><ChannelsPage /></RequirePermission>} />
        <Route path="/automations" element={<RequirePermission permission="rule:read"><RulesPage /></RequirePermission>} />
        <Route path="/automations/new" element={<RequirePermission permission="rule:read"><RuleEditorPage /></RequirePermission>} />
        <Route path="/automations/:id" element={<RequirePermission permission="rule:read"><RuleEditorPage /></RequirePermission>} />
        <Route path="/service-levels" element={<RequirePermission permission="settings:read"><SlaSettingsPage /></RequirePermission>} />
        <Route path="/audit" element={<RequirePermission permission="audit:read"><AuditPage /></RequirePermission>} />
      </Route>
      <Route path="*" element={<Navigate to="/inbox" replace />} />
    </Routes>
  )
}
