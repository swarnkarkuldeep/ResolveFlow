import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { Dialog } from '../ui'

function Host() {
  return (
    <>
      {/* A fresh inline onClose on every render, exactly like the real call sites. */}
      <Dialog title="Test dialog" onClose={() => undefined}>
        <label>
          First
          <input data-autofocus />
        </label>
        <label>
          Second
          <input />
        </label>
      </Dialog>
    </>
  )
}

describe('Dialog', () => {
  it('does not steal focus back when the parent re-renders while someone is typing', async () => {
    const { rerender } = render(<Host />)
    const second = screen.getByLabelText('Second')
    await userEvent.click(second)
    await userEvent.type(second, 'abc')
    // Simulate the inbox refetch: the parent re-renders with a new onClose identity.
    rerender(<Host />)
    await userEvent.keyboard('def')
    expect(second).toHaveFocus()
    expect(second).toHaveValue('abcdef')
  })

  it('still focuses the first field on open and closes on Escape', async () => {
    let closed = false
    render(
      <Dialog title="Another" onClose={() => (closed = true)}>
        <input aria-label="only" data-autofocus />
      </Dialog>,
    )
    expect(screen.getByLabelText('only')).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(closed).toBe(true)
  })
})
