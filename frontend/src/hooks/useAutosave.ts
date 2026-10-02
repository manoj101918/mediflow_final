import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/lib/api'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'

export type SaveState = 'saved' | 'dirty' | 'saving' | 'error'

/**
 * Debounced autosave of `payload`. Saves run one at a time, in order, and only when the
 * payload differs from what was last saved. `flush()` saves immediately (e.g. before
 * completing) and resolves once everything is stored.
 */
export function useAutosave<T>(
  payload: T,
  save: (payload: T) => Promise<unknown>,
  { enabled, delayMs = 800 }: { enabled: boolean; delayMs?: number },
) {
  const serialized = JSON.stringify(payload)
  const lastSaved = useRef(serialized)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const saveRef = useRef(save)
  useEffect(() => {
    saveRef.current = save
  }, [save])
  const [state, setState] = useState<SaveState>('saved')
  const [error, setError] = useState<string | null>(null)

  const run = useCallback((snapshot: string): Promise<void> => {
    // A failed save must not block later ones.
    queue.current = queue.current.catch(() => undefined).then(async () => {
      if (snapshot === lastSaved.current) return
      setState('saving')
      try {
        await saveRef.current(JSON.parse(snapshot) as T)
        lastSaved.current = snapshot
        setError(null)
        setState('saved')
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not save. Retrying on next change.')
        setState('error')
        throw err
      }
    })
    return queue.current
  }, [])

  const debounced = useDebouncedValue(serialized, delayMs)

  useEffect(() => {
    if (serialized !== lastSaved.current && state === 'saved') setState('dirty')
  }, [serialized, state])

  useEffect(() => {
    if (enabled && debounced !== lastSaved.current) run(debounced).catch(() => undefined)
  }, [debounced, enabled, run])

  const flush = useCallback(() => (enabled ? run(serialized) : Promise.resolve()), [enabled, run, serialized])

  return { state, error, flush }
}
