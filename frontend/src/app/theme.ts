import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'
const KEY = 'rf-theme'

function stored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

function system(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(() => stored() ?? system())

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === 'dark' ? 'light' : 'dark'
      try {
        window.localStorage.setItem(KEY, next)
      } catch {
        /* storage unavailable: the choice just lasts for this visit */
      }
      return next
    })
  }, [])

  return { theme, toggle }
}
