# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Explicit D3 capabilities, independent of the Gateway's larger internal registry."""
INTERRUPT_ACTIONS = frozenset({'show_interrupt'})
TIBO_ACTIONS = frozenset({'show_tibo_page', 'ack_tibo_attention', 'get_tibo_attention'})
READ_ACTIONS = frozenset({'list_todos', 'get_current_item', 'get_context'})
WRITE_ACTIONS = READ_ACTIONS | frozenset({
    'create_todo', 'update_todo', 'complete_todo', 'reorder_todos',
    'set_current_item', 'set_pending_question', 'publish_suggestion', 'resolve_intent',
})


def actions_for(scope):
    if scope == 'butler:read':
        return READ_ACTIONS
    if scope == 'butler:write':
        return WRITE_ACTIONS
    raise ValueError('explicit Butler scope required')


def gateway_actions(scope):
    # Clarification is an internal Resolver result, never a public tool.
    return actions_for(scope) | ({'request_clarification'} if scope == 'butler:write' else set())
