// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
import { ACTIONS, createGatewayClient, isWrite } from './gateway-client.mjs'

const text = description => ({ type: 'string', description })
const requiredText = description => ({ ...text(description), required: true })
const todoId = requiredText('Stable todo_id from the latest Todo Core snapshot')
const fields = {
  show_interrupt: { title: requiredText('Printable English ASCII title, 1-47 characters'), message: requiredText('Printable English ASCII message, 1-47 characters') },
  show_tibo_page: {}, get_tibo_attention: {},
  ack_tibo_attention: {event_id: requiredText("Exact Tibo event id; only after explicit user acknowledgment"), event_revision: {type: "integer", required: true, description: "Exact Tibo event revision"}},
  list_todos: {}, get_current_item: {}, get_context: {}, get_dashboard_state: {},
  create_todo: { title: requiredText('Todo title'), due_at: text('Optional timezone-aware deadline; does not schedule a reminder'), remind_at: text('Explicit user-requested reminder time as timezone-aware ISO timestamp') },
  update_todo: { todo_id: todoId, title: text('New title'), status: { type: 'string', enum: ['pending', 'done', 'cancelled'] }, due_at: { oneOf: [{ type: 'string' }, { type: 'null' }], description: 'Deadline timestamp, or null to clear; does not schedule a reminder' }, remind_at: { oneOf: [{ type: 'string' }, { type: 'null' }], description: 'Explicit reminder timestamp, or null to clear' } },
  complete_todo: { todo_id: todoId }, delete_todo: { todo_id: todoId },
  reorder_todos: { todo_ids: { type: 'array', items: { type: 'string' }, required: true, description: 'Every todo_id exactly once in the desired order' } },
  set_current_item: { todo_id: { oneOf: [{ type: 'string' }, { type: 'null' }], required: true, description: 'Stable todo_id, or null to clear current item' } },
  set_pending_question: { question: { oneOf: [{ type: 'string' }, { type: 'null' }], required: true }, target_todo_id: { oneOf: [{ type: 'string' }, { type: 'null' }], required: true } },
  publish_suggestion: { text: requiredText('Short non-authoritative suggestion; never changes Todo order, status, or current item'), device_text: text('Optional explicit ASCII device text, at most 47 characters; original suggestion text is preserved'), expires_at: text('Optional timezone-aware suggestion expiry timestamp') },
  publish_attention_event: { title: requiredText('Concise ASCII event title, at most 47 characters'), message: requiredText('Concise ASCII event message, at most 47 characters'), kind: { type: 'string', enum: ['service', 'agent_result', 'suggestion', 'reminder'] }, todo_id: text('Required for reminder: pending Todo with an explicit remind_at') },
  ack_interrupt: { event_id: requiredText('Exact event_id from the latest snapshot'), event_revision: { type: 'integer', required: true, description: 'Exact revision of the attention event, distinct from expected_revision of Todo Core' } },
  resolve_intent: { original_user_message: requiredText('Exact original user expression, never a paraphrase'), source_hint: text('Optional non-authoritative hint'), conversation_ref: text('Optional non-sensitive conversation reference') },
}
export const TOOL_NAMES = Object.freeze(ACTIONS.map(action => `butler_${action}`))

export function registerTodoTools(rt, defineTool) {
  const config = rt.config.butlerGateway
  if (!config) return
  if (!Array.isArray(config.botIds) || !config.botIds.length || config.botIds.some(id => typeof id !== 'string' || !id)) {
    throw new Error('Butler requires an explicit Bot allowlist')
  }
  const allowed = new Set(config.botIds)
  if (config.tokenEnv !== undefined && (typeof config.tokenEnv !== 'string' || !/^BUTLER_[A-Z0-9_]+$/.test(config.tokenEnv))) {
    throw new Error('tokenEnv must be an explicitly chosen BUTLER_ environment variable name')
  }
  if (config.getToken !== undefined && config.tokenEnv !== undefined) throw new Error('Choose getToken or tokenEnv')
  const getToken = config.getToken ?? (config.tokenEnv ? () => process.env[config.tokenEnv] : undefined)
  const command = createGatewayClient({ ...config, getToken })
  if (config.allowedActions !== undefined && (!Array.isArray(config.allowedActions)
      || !config.allowedActions.length || new Set(config.allowedActions).size !== config.allowedActions.length
      || config.allowedActions.some(action => !ACTIONS.includes(action)))) {
    throw new Error('allowedActions must be a non-empty unique subset of Butler actions')
  }
  const candidates = config.naturalLanguageOnly === true ? ['get_context', 'resolve_intent'] : ACTIONS
  const actions = config.allowedActions === undefined ? candidates : candidates.filter(action => config.allowedActions.includes(action))
  const boundConversation = config.naturalLanguageOnly === true || config.bindConversation === true
  for (const action of actions) {
    const parameters = {
      request_id: requiredText('Unique operation id (1–80 letters/digits/_-). Keep unchanged for retries, including after timeout or Bot restart.'),
      expected_revision: { type: 'integer', ...(isWrite(action) ? { required: true } : {}), description: 'Revision from a fresh Todo Core snapshot. On CONFLICT read again; never silently overwrite.' },
      ...fields[action],
    }
    if (boundConversation && action === 'resolve_intent') delete parameters.conversation_ref
    rt.ctx.tools.register(defineTool({
      name: `butler_${action}`,
      description: (action === 'show_interrupt'
        ? 'Owner-delegated autonomous Interrupt: choose when to interrupt and choose the English content. No per-message reminder request is required. Only title and message, each printable ASCII up to 47 characters. No Todo mutation or automatic ACK; Hub acceptance is not proof of physical display.'
        : action === 'resolve_intent'
        ? 'Resolve every natural-language Todo request, even when clear, using exact original user wording. The resolver applies approved actions itself. Already structured API calls use direct tools without another model call.' + (boundConversation ? ' conversation_ref is bound by the runtime: omit it from tool arguments.' : '')
        : config.naturalLanguageOnly === true && action === 'get_context'
          ? 'Preflight revision only. This cannot answer a user request. After this call, always call butler_resolve_intent with the exact original user message, including reads and clarification.'
        : `Run ${action} directly through authenticated Butler Gateway without another LLM call. Todo authority remains shadow until migration is approved.`) + ' Tibo Detail is only for explicit user requests and requires no ACK; ack_tibo_attention requires explicit user confirmation and exact event id/revision, never infer it from refresh, time or activity. For counts, quote result.stats.total, result.stats.pending and result.stats.done verbatim, with result.revision. Never count the todos list yourself. Missing stats means unavailable, not permission to estimate. Total includes cancelled items.',
      parameters,
      output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: String(value) }] },
      async execute(args, exec) {
        await rt.load()
        const botId = rt.selfOf(exec.agent?.id)
        if (!allowed.has(botId) || !rt.botOf(botId)) return JSON.stringify({ ok: false, status: 'forbidden' })
        if (isWrite(action) && rt.readOnly() !== undefined) return JSON.stringify({ ok: false, status: 'read_only' })
        if (args === null || typeof args !== 'object' || Array.isArray(args)) return JSON.stringify({ ok: false, status: 'invalid_arguments' })
        const unknown = Object.keys(args).filter(key => !Object.hasOwn(parameters, key))
        if (unknown.length) return JSON.stringify({ ok: false, status: 'invalid_arguments',
          allowed_fields: Object.keys(parameters),
          instruction: 'No request was sent. Remove fields absent from allowed_fields; retain the exact original_user_message and request_id. conversation_ref, when absent from allowed_fields, is supplied by the runtime.' })
        const { request_id, expected_revision, ...business } = args
        if (boundConversation && action === 'resolve_intent') business.conversation_ref = botId
        try {
          const response = await command({ action, request_id, expected_revision, arguments: business })
          if (config.naturalLanguageOnly === true && action === 'get_context' && response.ok) {
            return JSON.stringify({ ...response, result: { revision: response.result.revision, authority: response.result.authority, next_action: 'resolve_intent', instruction: 'Send the exact user message to resolve_intent, even for reads or clarification. This preflight has not answered the user.' } })
          }
          return JSON.stringify(response)
        }
        catch { return JSON.stringify({ ok: false, status: 'invalid_request_or_auth_unavailable' }) }
      },
    }))
  }
}

