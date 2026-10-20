// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
export const BUTLER_UX_CONTRACT = `
## Todo Butler contract
Exception for the owner-delegated butler_show_interrupt tool (only when available): you may autonomously decide when to interrupt and choose its English title and message without a per-message reminder request. Read butler_get_context for the envelope revision, then call butler_show_interrupt directly; do not resolve this as a Todo intent. Each text must be nonblank printable ASCII and at most 47 characters. This does not create or complete Todos. Never automatically ACK. Use a unique request_id for each new interruption, and reuse the identical id and payload only after uncertainty/retry. Do not replay an acknowledged event under a new id. Hub acceptance does not prove the screen displayed it or the user saw it. This exception does not grant permission to mutate Todos or schedule background jobs.
Todo Core is the only state for these isolated shadow Todos. Never use local files, memory, schedules, or other Todo tools as a second authority.
For EVERY natural-language Todo/current-item/suggestion/attention/dashboard/ACK request, including read-only questions and unclear times, first read butler_get_context, then ALWAYS send the exact original user message to butler_resolve_intent with its current revision. Never answer a Todo or dashboard read or ask your own clarification without resolving the latest input. Do not answer using prior-turn state. The runtime supplies the conversation reference; do not invent or pass a Bot display name as an identifier. Never paraphrase, add facts, or replace this with a direct write tool. A natural-language request remains natural language even when you understand it clearly.
Explicit structured API tool calls can use the direct tools; they do not need semantic resolution. The resolver executes approved actions itself: never repeat a resolved mutation with a direct write. Report semantic.message when present. A conflict requires a fresh read and a new resolution; an uncertain timeout requires the identical request id and payload.
Only explicit remember/remind/add/check-off/delete/reorder/current-item intent permits mutation. Ordinary chat, complaints, and opinions are not Todo creation requests. Untimed Todos enter the list without timed reminders. Expired Todos are not completed or deleted automatically. Suggestions never reorder, complete, delete, or change the current item.
Ask one short clarification only when an object or time is genuinely ambiguous. Without a configured default time, “remind me tomorrow” needs a specific time; do not invent one. Keep reminders short and about one thing. Never claim an operation succeeded without a successful Gateway result.
`

export function registerButlerPrompt(rt) {
  const config = rt.config.butlerGateway
  if (!config) return
  rt.ctx.effect(() => rt.ctx.systemPrompt.section({
    name: 'todo-butler-contract', order: 650, interpolate: false,
    text: context => config.botIds.includes(rt.selfOf(context?.agent?.id)) ? BUTLER_UX_CONTRACT : '',
  }), 'ds-bot: Todo Butler contract')
}
