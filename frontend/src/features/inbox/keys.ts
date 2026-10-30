export interface KeyActions {
  move: (delta: number) => void
  open: () => void
  toggleSelect: () => void
  resolve: () => void
  assignMe: () => void
  focusFilter: () => void
  reply: () => void
  showHelp: () => void
}

export interface KeyBinding {
  key: string
  label: string
  description: string
  run: (actions: KeyActions) => void
}

/** Single source of truth: the help dialog renders this list and the handler dispatches from it. */
export const KEYS: KeyBinding[] = [
  { key: 'j', label: 'j', description: 'Move to the next ticket', run: (a) => a.move(1) },
  { key: 'k', label: 'k', description: 'Move to the previous ticket', run: (a) => a.move(-1) },
  { key: 'Enter', label: 'Enter', description: 'Open the ticket', run: (a) => a.open() },
  { key: 'x', label: 'x', description: 'Select or deselect the ticket', run: (a) => a.toggleSelect() },
  { key: 'e', label: 'e', description: 'Mark as resolved', run: (a) => a.resolve() },
  { key: 'a', label: 'a', description: 'Assign to me', run: (a) => a.assignMe() },
  { key: 'r', label: 'r', description: 'Reply to the open ticket', run: (a) => a.reply() },
  { key: 'f', label: 'f', description: 'Filter by priority', run: (a) => a.focusFilter() },
  { key: '?', label: '?', description: 'Show keyboard shortcuts', run: (a) => a.showHelp() },
]

const TEXT_TARGETS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

/** True when a keypress should be left alone: typing in a field, a modifier combo, or a dialog is open. */
export function shouldIgnoreKey(e: KeyboardEvent): boolean {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return true
  const t = e.target as HTMLElement | null
  if (t && (TEXT_TARGETS.has(t.tagName) || t.isContentEditable)) return true
  if (e.key === 'Enter' && t && (t.tagName === 'A' || t.tagName === 'BUTTON')) return true
  return false
}
