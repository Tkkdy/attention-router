// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { randomBytes } from 'node:crypto'
import { test } from 'node:test'
import { createGatewayClient } from './gateway-client.mjs'
import { registerTodoTools, TOOL_NAMES } from './register-tools.mjs'

test('explicit capability allowlist limits structured tools and keeps runtime conversation binding', () => {
  const definitions = new Map()
  const rt = {
    config: { butlerGateway: { origin: 'http://127.0.0.1:33102', botIds: ['b'], getToken: () => 'synthetic',
      naturalLanguageOnly: false, allowedActions: ['get_context', 'resolve_intent'], bindConversation: true } },
    ctx: { tools: { register: tool => definitions.set(tool.name, tool) } },
  }
  registerTodoTools(rt, definition => definition)
  assert.deepEqual([...definitions.keys()], ['butler_get_context', 'butler_resolve_intent'])
  assert.equal(Object.hasOwn(definitions.get('butler_resolve_intent').parameters, 'conversation_ref'), false)
  rt.config.butlerGateway.allowedActions = ['shell']
  assert.throws(() => registerTodoTools(rt, definition => definition), /allowedActions/)
})

async function endpoint(t, handler) {
  const server = createServer(handler)
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections() }))
  return `http://127.0.0.1:${server.address().port}`
}

test('structured calls use one authenticated HTTP command, preserve retry and conflict', async t => {
  const seen = []
  const token = randomBytes(24).toString('hex')
  const origin = await endpoint(t, async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    assert.equal(req.url, '/v1/butler/commands')
    assert.equal(req.headers.authorization, `Bearer ${token}`)
    seen.push(JSON.parse(body))
    res.writeHead(seen.length === 3 ? 409 : 200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(seen.length === 3
      ? { ok: false, status: 'conflict', error: { current_revision: 1 } }
      : { ok: true, status: 'ok', result: { authority: 'shadow', revision: 1 } }))
  })
  const command = createGatewayClient({ origin, getToken: () => token })
  const operation = { action: 'create_todo', request_id: 'test-create-1', expected_revision: 0, arguments: { title: 'Coursework' } }
  assert.equal((await command(operation)).result.authority, 'shadow')
  assert.equal((await command(operation)).ok, true)
  assert.deepEqual(seen[0], seen[1])
  assert.deepEqual(seen[0], { source: 'deepseek', ...operation })
  assert.equal((await command({ ...operation, request_id: 'test-create-2' })).status, 'conflict')
  assert.equal(seen.length, 3)
})

test('reject missing revision, unlisted actions, credentials in origin and non-loopback origins', async () => {
  for (const origin of ['https://127.0.0.1', 'http://localhost:9000', 'http://example.com', 'http://127.0.0.1/path', 'http://user:pass@127.0.0.1', 'http://127.0.0.1', 'http://127.0.0.1:3001', 'http://127.0.0.1:3101', 'http://127.0.0.1:8000']) {
    assert.throws(() => createGatewayClient({ origin, getToken: () => 'synthetic' }))
  }
  const command = createGatewayClient({ origin: 'http://127.0.0.1:65534', getToken: () => 'synthetic' })
  await assert.rejects(command({ action: 'create_todo', request_id: 'x' }), /revision/)
  await assert.rejects(command({ action: 'list_todos', request_id: 'unsafe.id:1' }), /request_id/)
  await assert.rejects(command({ action: 'shell', request_id: 'x', expected_revision: 1 }), /Unsupported/)
})

test('transport never follows redirects or retries a potentially committed write', async t => {
  let destinationCalls = 0
  const destination = await endpoint(t, (_req, res) => { destinationCalls++; res.end('{}') })
  let sourceCalls = 0
  const origin = await endpoint(t, (_req, res) => {
    sourceCalls++
    res.writeHead(307, { Location: destination }); res.end()
  })
  const command = createGatewayClient({ origin, getToken: () => 'synthetic' })
  const result = await command({ action: 'complete_todo', request_id: 'retry-me', expected_revision: 0, arguments: { todo_id: 'x' } })
  assert.equal(result.status, 'transport_error')
  assert.match(result.error, /identical request_id/)
  assert.equal(sourceCalls, 1)
  assert.equal(destinationCalls, 0)
})

test('timeout preserves uncertainty without credential leakage', async t => {
  const origin = await endpoint(t, (_req, _res) => {})
  const command = createGatewayClient({ origin, getToken: () => 'never-return-this', timeoutMs: 20 })
  assert.equal((await command({ action: 'list_todos', request_id: 'read' })).status, 'transport_error')
})

test('registration is disabled by default, allowlists Bot identity and respects read-only hosts', async t => {
  let calls = 0
  const origin = await endpoint(t, (_req, res) => { calls++; res.end(JSON.stringify({ ok: true, status: 'ok', result: {} })) })
  const definitions = new Map()
  let readOnly
  const rt = {
    config: {}, load: async () => {}, selfOf: session => session === 's1' ? 'b1' : undefined,
    botOf: id => id === 'b1' ? { id } : undefined, readOnly: () => readOnly,
    ctx: { tools: { register: tool => definitions.set(tool.name, tool) } },
  }
  registerTodoTools(rt, definition => definition)
  assert.equal(definitions.size, 0)
  rt.config.butlerGateway = { origin, getToken: () => 'synthetic', botIds: ['b1'] }
  registerTodoTools(rt, definition => definition)
  assert.deepEqual([...definitions.keys()], TOOL_NAMES)
  const read = definitions.get('butler_list_todos')
  const create = definitions.get('butler_create_todo')
  assert.equal('required' in read.parameters.expected_revision, false)
  assert.equal(create.parameters.expected_revision.required, true)
  assert.equal(JSON.parse(await read.execute({ request_id: 'read' }, { agent: { id: 'foreign' } })).status, 'forbidden')
  readOnly = 'Another host owns this Bot state'
  assert.equal(JSON.parse(await create.execute({ request_id: 'write', expected_revision: 0, title: 'x' }, { agent: { id: 's1' } })).status, 'read_only')
  assert.equal(calls, 0)
  assert.equal(JSON.parse(await read.execute({ request_id: 'read', source: 'grok' }, { agent: { id: 's1' } })).status, 'invalid_arguments')
  assert.equal(JSON.parse(await read.execute({ request_id: 'read' }, { agent: { id: 's1' } })).ok, true)
  assert.equal(calls, 1)
})


test('explicit tokenEnv reads only a synthetic child environment, never the model arguments', async t => {
  const { spawn } = await import('node:child_process')
  const token = randomBytes(24).toString('hex')
  let calls = 0
  const origin = await endpoint(t, (req, res) => {
    assert.equal(req.headers.authorization, `Bearer ${token}`)
    calls++
    res.end(JSON.stringify({ ok: true, status: 'ok', result: {} }))
  })
  const script = `
    const { registerTodoTools } = await import(${JSON.stringify(new URL('./register-tools.mjs', import.meta.url).href)})
    const tools = new Map()
    const rt = {
      config: { butlerGateway: { origin: ${JSON.stringify(origin)}, botIds: ['test'], tokenEnv: 'BUTLER_TEST_GATEWAY_TOKEN' } },
      ctx: { tools: { register: tool => tools.set(tool.name, tool) } },
      load: async () => {}, selfOf: () => 'test', botOf: () => ({ id: 'test' }), readOnly: () => undefined,
    }
    registerTodoTools(rt, definition => definition)
    const result = JSON.parse(await tools.get('butler_list_todos').execute({ request_id: 'env_read' }, { agent: { id: 'test' } }))
    if (!result.ok) process.exitCode = 1
  `
  const child = spawn(process.execPath, ['--input-type=module', '-e', script], {
    env: { ...process.env, BUTLER_TEST_GATEWAY_TOKEN: token }, windowsHide: true, stdio: 'ignore',
  })
  assert.equal(await new Promise(resolve => child.once('exit', resolve)), 0)
  assert.equal(calls, 1)
  assert.throws(() => registerTodoTools({
    config: { butlerGateway: { origin, botIds: ['test'], tokenEnv: 'DEEPSEEK_API_KEY' } },
  }, definition => definition), /tokenEnv/)
})

test('natural-language Bot entry exposes only context and resolver; structured adapter stays direct', () => {
  const definitions = new Map()
  const rt = {
    config: { butlerGateway: { origin: 'http://127.0.0.1:33102', botIds: ['b'], getToken: () => 'synthetic', naturalLanguageOnly: true } },
    ctx: { tools: { register: tool => definitions.set(tool.name, tool) } },
  }
  registerTodoTools(rt, definition => definition)
  assert.deepEqual([...definitions.keys()], ['butler_get_context', 'butler_resolve_intent'])
  definitions.clear()
  rt.config.butlerGateway.naturalLanguageOnly = false
  registerTodoTools(rt, definition => definition)
  assert.deepEqual([...definitions.keys()], TOOL_NAMES)
})

test('natural-language preflight reveals only revision so reads still require the resolver', async t => {
  const origin = await endpoint(t, (_req, res) => res.end(JSON.stringify({ ok: true, status: 'ok', result: { revision: 7, authority: 'shadow', todos: [{ title: 'private test title' }], context: { pending_question: 'synthetic' } } })))
  const definitions = new Map()
  const rt = {
    config: { butlerGateway: { origin, botIds: ['b'], getToken: () => 'synthetic', naturalLanguageOnly: true } },
    ctx: { tools: { register: tool => definitions.set(tool.name, tool) } },
    load: async () => {}, selfOf: () => 'b', botOf: () => ({ id: 'b' }), readOnly: () => undefined,
  }
  registerTodoTools(rt, definition => definition)
  const raw = await definitions.get('butler_get_context').execute({ request_id: 'preflight' }, { agent: { id: 'b' } })
  assert.equal(JSON.parse(raw).result.revision, 7)
  assert.equal(JSON.parse(raw).result.next_action, 'resolve_intent')
  assert.equal(raw.includes('private test title'), false)
  assert.equal(Object.hasOwn(JSON.parse(raw).result, 'context'), false)
})



test('natural-language conversation reference is bound by runtime, not the model display name', async t => {
  let received
  const origin = await endpoint(t, async (req, res) => {
    let body=''; for await (const chunk of req) body+=chunk
    received=JSON.parse(body)
    res.end(JSON.stringify({ok:true,status:'ok',result:{revision:1}}))
  })
  const definitions=new Map()
  const rt={
    config:{butlerGateway:{origin,botIds:['bot-stable-id'],getToken:()=> 'synthetic',naturalLanguageOnly:true}},
    ctx:{tools:{register:tool=>definitions.set(tool.name,tool)}},
    load:async()=>{},selfOf:()=> 'bot-stable-id',botOf:()=>({id:'bot-stable-id'}),readOnly:()=>undefined,
  }
  registerTodoTools(rt,definition=>definition)
  const resolver=definitions.get('butler_resolve_intent')
  assert.equal(Object.hasOwn(resolver.parameters,'conversation_ref'),false)
  const original='Remember this test'
  const rejected=JSON.parse(await resolver.execute({request_id:'test',expected_revision:0,original_user_message:original,conversation_ref:'old-model-value'},{agent:{id:'s'}}))
  assert.equal(rejected.status,'invalid_arguments')
  assert.equal(rejected.allowed_fields.includes('conversation_ref'),false)
  assert.equal(received,undefined)
  assert.equal(JSON.parse(await resolver.execute({request_id:'test',expected_revision:0,original_user_message:original},{agent:{id:'s'}})).ok,true)
  assert.equal(received.arguments.conversation_ref,'bot-stable-id')
  assert.equal(received.arguments.original_user_message,original)
})
