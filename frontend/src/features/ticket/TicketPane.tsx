import type { To } from 'react-router-dom'

export function TicketPane({ ticketId }: { ticketId: string; backTo: To }) {
  return (
    <div data-testid="ticket-pane" data-ticket-id={ticketId} className="p-6">
      Ticket {ticketId}
    </div>
  )
}
