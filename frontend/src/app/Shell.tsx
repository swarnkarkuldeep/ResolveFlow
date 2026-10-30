import { Inbox, LogOut, Moon, Plug, ScrollText, Sun, Timer, Users } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { Avatar } from '../ui'
import { ROLE_LABEL } from '../lib/types'
import { useAuth } from './auth'
import { useTheme } from './theme'

const ITEMS = [
  { to: '/inbox', label: 'Inbox', icon: Inbox, perm: null },
  { to: '/people', label: 'People', icon: Users, perm: 'user:read' },
  { to: '/channels', label: 'Channels', icon: Plug, perm: 'settings:read' },
  { to: '/service-levels', label: 'Service levels', icon: Timer, perm: 'settings:read' },
  { to: '/audit', label: 'Audit log', icon: ScrollText, perm: 'audit:read' },
] as const

const RAIL_BUTTON =
  'flex h-10 w-10 items-center justify-center rounded-control text-rail-ink transition-colors hover:bg-white/10 hover:text-white'

export function Shell() {
  const { me, can, logout, switchWorkspace } = useAuth()
  const { theme, toggle } = useTheme()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setMenuOpen(false)
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [menuOpen])

  const workspace = me?.active_workspace

  return (
    <div className="flex h-full flex-col-reverse md:flex-row">
      <nav
        aria-label="Main"
        className="relative flex h-14 shrink-0 items-center justify-around bg-rail px-2 md:h-full md:w-14 md:flex-col md:justify-start md:gap-1 md:px-0 md:py-3"
      >
        <span
          aria-hidden="true"
          title={workspace?.name}
          className="hidden h-9 w-9 items-center justify-center rounded-control bg-accent text-[15px] font-semibold text-accent-ink md:mb-3 md:flex"
        >
          {workspace?.name?.[0]?.toUpperCase() ?? 'R'}
        </span>
        {ITEMS.filter((i) => !i.perm || can(i.perm)).map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            aria-label={label}
            title={label}
            className={({ isActive }) =>
              `${RAIL_BUTTON} ${isActive ? 'bg-white/12 !text-white shadow-[inset_2px_0_0_var(--accent)]' : ''}`
            }
          >
            <Icon size={19} strokeWidth={1.9} aria-hidden="true" />
          </NavLink>
        ))}
        <div className="md:mt-auto" />
        <button
          type="button"
          onClick={toggle}
          className={RAIL_BUTTON}
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
        >
          {theme === 'dark' ? <Sun size={19} aria-hidden="true" /> : <Moon size={19} aria-hidden="true" />}
        </button>
        <div ref={menuRef} className="md:mt-1">
          <button
            type="button"
            aria-label="Account menu"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((o) => !o)}
            className="flex h-10 w-10 items-center justify-center rounded-full hover:bg-white/10"
          >
            <Avatar name={me?.user.name} size={30} />
          </button>
          {menuOpen && me && (
            <div
              role="menu"
              className="pane-in absolute bottom-14 right-2 z-40 w-64 rounded-panel border border-line bg-paper p-2 text-ink md:bottom-2 md:left-14 md:right-auto"
            >
              <div className="px-2.5 py-2">
                <p className="text-[14px] font-medium">{me.user.name}</p>
                <p className="text-[13px] text-slate">{me.user.email}</p>
                <p className="mt-0.5 text-[13px] text-slate">
                  {workspace?.name} · {me.role ? ROLE_LABEL[me.role] : ''}
                </p>
              </div>
              {me.workspaces.length > 1 && (
                <div className="border-t border-line py-1">
                  {me.workspaces.map((w) => (
                    <button
                      key={w.id}
                      role="menuitem"
                      type="button"
                      disabled={w.id === workspace?.id}
                      onClick={async () => {
                        setMenuOpen(false)
                        await switchWorkspace(w.id)
                      }}
                      className="flex w-full items-center justify-between rounded-control px-2.5 py-1.5 text-left text-[14px] hover:bg-wash disabled:text-slate"
                    >
                      {w.name}
                      {w.id === workspace?.id && <span className="text-[12px] text-slate">Current</span>}
                    </button>
                  ))}
                </div>
              )}
              <div className="border-t border-line pt-1">
                <button
                  role="menuitem"
                  type="button"
                  onClick={() => logout()}
                  className="flex w-full items-center gap-2 rounded-control px-2.5 py-1.5 text-left text-[14px] hover:bg-wash"
                >
                  <LogOut size={15} aria-hidden="true" /> Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </nav>
      <main className="min-h-0 min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
