// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
import { defineTool } from '@deepseek-ai/dsh-tools'
import { registerTodoTools } from './register-tools.mjs'
import { registerButlerPrompt } from './ux-contract.mjs'

// Called by DS Bot's MODULES list with its existing Session/store runtime.
export function install(rt) {
  registerTodoTools(rt, defineTool)
  registerButlerPrompt(rt)
}

