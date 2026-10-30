import { useState } from 'react'

import { useToast } from '../../app/Toasts'
import { Button, Dialog, Field, FormError, Select } from '../../ui'
import { useMerge, useMergeCandidates } from './queries'

export function MergeDialog({
  ticketId,
  number,
  onClose,
  onMerged,
}: {
  ticketId: string
  number: number
  onClose: () => void
  onMerged: (intoId: string) => void
}) {
  const candidates = useMergeCandidates(ticketId, true)
  const merge = useMerge(ticketId)
  const toast = useToast()
  const [target, setTarget] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = () => {
    setError(null)
    merge.mutate(target, {
      onSuccess: () => {
        toast('Tickets merged')
        onMerged(target)
      },
      onError: (e) => setError(e.message),
    })
  }

  return (
    <Dialog title={`Merge ticket #${number}`} onClose={onClose}>
      <p className="mb-4 text-[14px] text-slate">
        All messages move into the ticket you choose, and this ticket is closed. This cannot be undone.
      </p>
      <Field label="Merge into" htmlFor="merge-target">
        <Select id="merge-target" data-autofocus value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">{candidates.isPending ? 'Loading tickets…' : 'Choose a ticket'}</option>
          {candidates.data?.map((t) => (
            <option key={t.id} value={t.id}>
              #{t.number} {t.subject} — {t.requester.name || t.requester.email}
            </option>
          ))}
        </Select>
      </Field>
      <div className="mt-3">
        <FormError message={error} />
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={submit} disabled={!target || merge.isPending}>
          {merge.isPending ? 'Merging…' : 'Merge tickets'}
        </Button>
      </div>
    </Dialog>
  )
}
