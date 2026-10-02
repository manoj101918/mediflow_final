import { useEffect, useRef } from 'react'

type HotkeyMap = Record<string, (event: KeyboardEvent) => void>

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
    target.closest('[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]') !==
      null
  )
}

/** Single-key shortcuts (e.g. "n", "/") that never fire while typing or inside a dialog. */
export function useHotkeys(map: HotkeyMap) {
  const mapRef = useRef(map)
  useEffect(() => {
    mapRef.current = map
  }, [map])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return
      const handler = mapRef.current[event.key.toLowerCase()]
      if (handler) {
        event.preventDefault()
        handler(event)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])
}
