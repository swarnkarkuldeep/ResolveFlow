import { Dialog } from '../../ui'
import { KEYS } from './keys'

export function ShortcutsDialog({ onClose, extra = [] }: { onClose: () => void; extra?: { label: string; description: string }[] }) {
  const all = [...KEYS.map((k) => ({ label: k.label, description: k.description })), ...extra]
  return (
    <Dialog title="Keyboard shortcuts" onClose={onClose} width={420}>
      <ul className="flex flex-col gap-2">
        {all.map((k) => (
          <li key={k.label + k.description} className="flex items-center justify-between gap-6 text-[14px]">
            <span>{k.description}</span>
            <kbd className="min-w-7 rounded-[5px] border border-line bg-wash px-2 py-0.5 text-center font-sans text-[12px] text-slate">{k.label}</kbd>
          </li>
        ))}
      </ul>
    </Dialog>
  )
}
