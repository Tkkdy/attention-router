// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
const READS = new Set(['list_todos', 'get_current_item', 'get_context', 'get_dashboard_state', 'get_tibo_attention'])
export const ACTIONS = Object.freeze([
  ...READS, 'show_tibo_page', 'ack_tibo_attention', 'create_todo', 'update_todo', 'complete_todo', 'delete_todo',
  'reorder_todos', 'set_current_item', 'set_pending_question', 'publish_suggestion', 'publish_attention_event', 'ack_interrupt', 'resolve_intent',
])
export const isWrite = action => !READS.has(action)

export function createGatewayClient({ origin, getToken, timeoutMs = 5000 }) {
  const url = new URL(origin)
  if (url.protocol !== 'http:' || !['127.0.0.1', '[::1]'].includes(url.hostname)
      || !url.port || Number(url.port) < 1024 || ['3001', '3101', '8000'].includes(url.port)
      || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Butler Gateway must use a literal loopback HTTP origin')
  }
  if (typeof getToken !== 'function') throw new Error('A host-owned token provider is required')
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000) throw new Error('Invalid timeout')
  const endpoint = new URL('/v1/butler/commands', url)

  return async function command({ action, request_id, expected_revision, arguments: args = {} }) {
    if (!ACTIONS.includes(action)) throw new Error('Unsupported Butler action')
    if (typeof request_id !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(request_id)) throw new Error('Invalid request_id')
    if ((isWrite(action) || expected_revision !== undefined)
        && (!Number.isSafeInteger(expected_revision) || expected_revision < 0)) throw new Error('A current expected_revision is required')
    if (args === null || typeof args !== 'object' || Array.isArray(args)) throw new Error('Arguments must be an object')
    const token = await getToken()
    if (typeof token !== 'string' || !token || /\s/.test(token)) throw new Error('Butler authentication is unavailable')
    const body = JSON.stringify({ source: 'deepseek', action, request_id, expected_revision, arguments: args })
    if (Buffer.byteLength(body) > 65536) throw new Error('Butler request is too large')
    try {
      const response = await fetch(endpoint, {
        method: 'POST', redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body,
      })
      const reader = response.body?.getReader()
      if (!reader) throw new Error('Missing response')
      const chunks = []
      let size = 0
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          size += value.length
          if (size > 1048576) throw new Error('Response too large')
          chunks.push(value)
        }
      } finally { await reader.cancel().catch(() => {}) }
      const text = Buffer.concat(chunks).toString('utf8').split(token).join('[redacted]')
      const data = JSON.parse(text)
      if (!data || typeof data.ok !== 'boolean' || data.ok !== response.ok) throw new Error('Invalid response')
      return data
    } catch {
      // A timeout may follow a committed write; callers must keep the same request_id.
      return { ok: false, status: 'transport_error', error: 'Butler response unavailable. Retry the identical request_id and payload; do not assume a write failed.' }
    }
  }
}

