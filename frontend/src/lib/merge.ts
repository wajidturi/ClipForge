/** A cursor page as returned by list endpoints. */
export type Page<T> = { items: T[]; next_cursor: string | null }

type Row = { id: string; updated_at: string }

/**
 * Merge one pushed row into a cached page: replace it if present, otherwise add on top.
 * Events can arrive out of order, so newer data is never replaced by older data.
 */
export function mergeItem<T extends Row>(page: Page<T> | undefined, item: T): Page<T> {
  const items = page?.items ?? []
  const idx = items.findIndex((x) => x.id === item.id)
  if (idx === -1) return { items: [item, ...items], next_cursor: page?.next_cursor ?? null }
  if (items[idx].updated_at > item.updated_at) return page ?? { items, next_cursor: null }
  const next = items.slice()
  next[idx] = item
  return { items: next, next_cursor: page?.next_cursor ?? null }
}

export function removeItem<T extends Row>(
  page: Page<T> | undefined,
  id: string,
): Page<T> | undefined {
  return page && { ...page, items: page.items.filter((x) => x.id !== id) }
}
