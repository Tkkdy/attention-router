// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { registerTodoTools, TOOL_NAMES } from './register-tools.mjs'

if (!process.argv[2]) throw new Error('Pass the isolated, built DeepSeek Harness checkout')
const require = createRequire(resolve(process.argv[2], 'packages/bundle/base/package.json'))
const { defineTool } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-tools')))
const tools = new Map()
registerTodoTools({
  config: { butlerGateway: { origin: 'http://127.0.0.1:33102', botIds: ['fixture-bot'], getToken: () => { throw new Error('No network call expected') } } },
  ctx: { tools: { register: tool => tools.set(tool.name, tool) } },
  load: async () => {}, selfOf: () => undefined, botOf: () => undefined, readOnly: () => undefined,
}, defineTool)
assert.deepEqual([...tools.keys()], TOOL_NAMES)
assert.deepEqual(tools.get('butler_set_current_item').parameters.properties.todo_id.oneOf, [{ type: 'string' }, { type: 'null' }])
assert.ok(tools.get('butler_create_todo').parameters.required.includes('expected_revision'))
assert.equal(tools.get('butler_list_todos').parameters.required.includes('expected_revision'), false)
console.log(`PASS: all ${TOOL_NAMES.length} Butler tools compile with real DSH defineTool; this does not start a Bot Session.`)

