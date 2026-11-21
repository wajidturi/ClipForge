import { vi } from 'vitest'

type Handler = (req: Request) => unknown | Promise<unknown>
type Route = { method: string; path: RegExp; status?: number; handler: Handler }

/** Route fetch() calls by method + path regex; records every request. */
export function mockApi(routes: Route[]) {
  const calls: { method: string; path: string; body: unknown }[] = []
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const req = input instanceof Request ? input : new Request(String(input))
    const path = new URL(req.url).pathname
    const text = req.method === 'GET' ? '' : await req.clone().text()
    calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined })
    const route = routes.find((r) => r.method === req.method && r.path.test(path))
    if (!route)
      return new Response(JSON.stringify({ detail: `no mock for ${path}` }), { status: 404 })
    const data = await route.handler(req)
    return new Response(JSON.stringify(data), {
      status: route.status ?? 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  return { calls, spy }
}
