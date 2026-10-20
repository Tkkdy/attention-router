// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
import assert from 'node:assert/strict'
import { createGatewayClient } from './gateway-client.mjs'
let input = ''
for await (const chunk of process.stdin) input += chunk
const { origin, deepseek, grok } = JSON.parse(input)
const options = { origin, getToken: () => deepseek }
let command = createGatewayClient(options)
const read = () => command({ action: 'list_todos', request_id: 'read' })
const grokCall = async body => (await fetch(new URL('/v1/butler/commands', origin), {
  method: 'POST', headers: { Authorization: `Bearer ${grok}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ source: 'grok', ...body }),
})).json()
assert.equal((await read()).result.revision, 0)
const create = { action: 'create_todo', request_id: 'deepseek_create', expected_revision: 0, arguments: { title: 'Cross-entry fixture' } }
const created = await command(create)
assert.equal(created.ok, true)
assert.equal(created.result.authority, 'shadow')
const todo = created.result.todos[0].todo_id
const fromGrok = await grokCall({ action: 'list_todos', request_id: 'grok_read', arguments: {} })
assert.equal(fromGrok.result.todos[0].todo_id, todo)
assert.equal((await grokCall({ action: 'complete_todo', request_id: 'grok_complete', expected_revision: 1, arguments: { todo_id: todo } })).ok, true)
assert.equal((await read()).result.todos[0].status, 'done')
assert.equal((await command({ action: 'update_todo', request_id: 'stale', expected_revision: 1, arguments: { todo_id: todo, title: 'Must not overwrite' } })).status, 'conflict')
command = createGatewayClient(options)
assert.equal((await command(create)).ok, true)
assert.equal((await read()).result.todos.length, 1)
assert.equal((await command({ action: 'set_pending_question', request_id: 'pending', expected_revision: 2, arguments: { question: 'Continue this task?', target_todo_id: todo } })).ok, true)
assert.equal((await grokCall({ action: 'get_context', request_id: 'grok_context', arguments: {} })).result.context.pending_question_target, todo)
const resolved = await command({ action: 'resolve_intent', request_id: 'intent', expected_revision: 3, arguments: { original_user_message: 'Do that next' } })
assert.equal(resolved.status, 'semantic_resolver_unavailable')
assert.equal((await read()).result.revision, 3)
console.log('PASS: real Node adapter -> authenticated Python Gateway -> isolated SQLite; cross-entry, stale conflict, retry after client recreation, shared question; no real Bot/LLM/device.')

