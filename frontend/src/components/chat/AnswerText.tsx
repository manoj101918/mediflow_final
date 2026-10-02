import { Fragment, type ReactNode } from 'react'

import { cn } from '@/lib/utils'
import type { Citation } from '@/types/api'

/**
 * Renders the assistant's answer: paragraphs, bullet/numbered lists, Markdown tables,
 * **bold**, `code`, and [n] citation markers as clickable references. Built from React
 * elements only (no HTML injection from model output).
 */
export function AnswerText({
  text,
  citations,
  onCite,
}: {
  text: string
  citations: Citation[]
  onCite: (citation: Citation) => void
}) {
  const byNumber = new Map(citations.map((c) => [c.n, c]))
  const inline = (value: string) => renderInline(value, byNumber, onCite)
  return <div className="space-y-2 text-sm leading-relaxed">{blocks(text).map((b, i) => renderBlock(b, i, inline))}</div>
}

type Block =
  | { kind: 'p'; lines: string[] }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'table'; rows: string[][] }

function blocks(text: string): Block[] {
  const out: Block[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const last = out.at(-1)
    if (!line.trim()) {
      out.push({ kind: 'p', lines: [] })
      continue
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      if (/^\s*\|[\s:|-]+\|\s*$/.test(line)) continue // header separator
      const cells = line.trim().slice(1, -1).split('|').map((c) => c.trim())
      if (last?.kind === 'table') last.rows.push(cells)
      else out.push({ kind: 'table', rows: [cells] })
      continue
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (bullet || numbered) {
      const kind = bullet ? 'ul' : 'ol'
      const item = (bullet ?? numbered)![1]!
      if (last?.kind === kind) last.items.push(item)
      else out.push({ kind, items: [item] })
      continue
    }
    if (last?.kind === 'p') last.lines.push(line)
    else out.push({ kind: 'p', lines: [line] })
  }
  return out.filter((b) => b.kind !== 'p' || b.lines.length > 0)
}

function renderBlock(block: Block, key: number, inline: (value: string) => ReactNode) {
  switch (block.kind) {
    case 'p':
      return (
        <p key={key}>
          {block.lines.map((line, i) => (
            <Fragment key={i}>
              {i > 0 && <br />}
              {inline(line)}
            </Fragment>
          ))}
        </p>
      )
    case 'ul':
    case 'ol': {
      const List = block.kind
      return (
        <List key={key} className={cn('space-y-0.5 pl-5', block.kind === 'ul' ? 'list-disc' : 'list-decimal')}>
          {block.items.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </List>
      )
    }
    case 'table': {
      const [head, ...body] = block.rows
      return (
        <div key={key} className="overflow-x-auto rounded-md border">
          <table className="w-full text-xs">
            <thead className="bg-muted/60">
              <tr>
                {head!.map((cell, i) => (
                  <th key={i} className="px-2 py-1 text-left font-medium">
                    {inline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, r) => (
                <tr key={r} className="border-t">
                  {row.map((cell, i) => (
                    <td key={i} className="px-2 py-1 tabular-nums">
                      {inline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }
  }
}

// [2], [2, 4], and [2†L3-L5] (some models add a locator; it is not shown).
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d{1,3}(?:\s*,\s*\d{1,3})*(?:†[^\]]*)?\])/g

function renderInline(
  value: string,
  citations: Map<number, Citation>,
  onCite: (citation: Citation) => void,
): ReactNode[] {
  return value.split(INLINE).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code key={i} className="rounded bg-muted px-1 text-xs">
          {part.slice(1, -1)}
        </code>
      )
    }
    const marker = /^\[(\d{1,3}(?:\s*,\s*\d{1,3})*)(?:†[^\]]*)?\]$/.exec(part)
    if (marker) {
      return (
        <Fragment key={i}>
          {marker[1]!.split(',').map((raw) => {
            const n = Number(raw.trim())
            const citation = citations.get(n)
            return citation ? (
              <button
                key={n}
                type="button"
                onClick={() => onCite(citation)}
                className="mx-0.5 rounded bg-primary/10 px-1 align-super text-[10px] font-semibold text-primary hover:bg-primary/20"
                title={citation.label}
                data-citation-marker={n}
              >
                {n}
              </button>
            ) : (
              <sup key={n} className="mx-0.5 text-[10px] text-muted-foreground">
                {n}
              </sup>
            )
          })}
        </Fragment>
      )
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}
