import { useQuery } from '@tanstack/react-query'
import { Loader2Icon, MessagesSquareIcon } from 'lucide-react'
import { useState } from 'react'

import { ChatTranscript } from '@/components/bot/ChatTranscript'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { LANGUAGE_LABEL, botKeys, fetchAppointmentConversation, fetchConversation } from '@/lib/bot'
import type { Appointment } from '@/types/api'

/** "View chat" for a WhatsApp / voice booking: the conversation it came from, read-only. */
export function ViewChatButton({ appointment }: { appointment: Appointment }) {
  const [open, setOpen] = useState(false)
  if (appointment.source !== 'whatsapp' && appointment.source !== 'voice') return null
  return (
    <>
      <Button variant="link" size="sm" className="h-auto px-0" onClick={() => setOpen(true)} data-view-chat={appointment.id}>
        <MessagesSquareIcon />
        View chat
      </Button>
      {open && <ChatDialog appointment={appointment} onClose={() => setOpen(false)} />}
    </>
  )
}

function ChatDialog({ appointment, onClose }: { appointment: Appointment; onClose: () => void }) {
  const ref = useQuery({
    queryKey: botKeys.forAppointment(appointment.id),
    queryFn: ({ signal }) => fetchAppointmentConversation(appointment.id, signal),
  })
  const conversationId = ref.data?.conversation_id ?? null
  const detail = useQuery({
    queryKey: botKeys.conversation(conversationId ?? 'none'),
    queryFn: ({ signal }) => fetchConversation(conversationId!, signal),
    enabled: conversationId !== null,
  })
  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Chat with {appointment.patient.full_name}</DialogTitle>
          <DialogDescription>
            {appointment.source === 'whatsapp' ? 'WhatsApp' : 'Voice bot'}
            {detail.data?.language ? ` · ${LANGUAGE_LABEL[detail.data.language]}` : ''}
            {detail.data ? ` · ${detail.data.phone}` : ''}
          </DialogDescription>
        </DialogHeader>
        {ref.isPending || detail.isLoading ? (
          <Loader2Icon className="mx-auto size-5 animate-spin text-muted-foreground" />
        ) : conversationId === null ? (
          <p className="text-sm text-muted-foreground">No chat was found for this booking.</p>
        ) : (
          <ChatTranscript messages={detail.data?.messages ?? []} />
        )}
      </DialogContent>
    </Dialog>
  )
}
