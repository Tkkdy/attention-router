// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { BUTLER_UX_CONTRACT, registerButlerPrompt } from './ux-contract.mjs'

test('Butler prompt is disabled by default and only reaches allowlisted Bot sessions', () => {
  let section
  const rt = { config: {}, selfOf: id => id === 'session' ? 'butler' : id, ctx: { effect: fn => fn(), systemPrompt: { section: value => { section = value } } } }
  registerButlerPrompt(rt)
  assert.equal(section, undefined)
  rt.config.butlerGateway = { botIds: ['butler'] }
  registerButlerPrompt(rt)
  assert.equal(section.text({ agent: { id: 'session' } }), BUTLER_UX_CONTRACT)
  assert.equal(section.text({ agent: { id: 'other' } }), '')
  assert.equal(section.text({}), '')
})
