# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Grok's narrow client for the isolated Butler Gateway.

This does not register public MCP tools or alter the production OAuth policy.
A future authenticated MCP handler can pass one of these tool calls to call_tool.
Credentials are injected at construction and are never persisted or logged.
"""
from copy import deepcopy
import re
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError
try:
    from .butler_models import Command, READS, SCHEMAS
except ImportError:
    from butler_models import Command, READS, SCHEMAS


_READS = READS
_PUBLIC_ACTIONS = set(SCHEMAS) - {'request_clarification'}
_ID = {'type': 'string', 'minLength': 1, 'maxLength': 80, 'pattern': '^[A-Za-z0-9_-]+$'}

def tool_definitions():
    """MCP-compatible JSON tool definitions; no shell/SQL/device/Scene surfaces."""
    result = []
    for action, schema in SCHEMAS.items():
        if action not in _PUBLIC_ACTIONS:
            continue
        required_envelope = ['request_id', 'arguments']
        if action not in _READS:
            required_envelope.append('expected_revision')
        result.append({'name': action, 'description': (
            'Show Tibo Detail only on explicit user request; no acknowledgment required.' if action == 'show_tibo_page'
            else 'Acknowledge only the exact Tibo event the user explicitly said they saw; never infer from refresh/time/activity. No Todo mutation.' if action == 'ack_tibo_attention'
            else 'Read Tibo event ids, revisions and acknowledgment stages; never infer seen from display.' if action == 'get_tibo_attention'
            else 'Resolve original, ambiguous user intent via the shared Semantic Resolver.' if action == 'resolve_intent'
            else f'{action}: deterministic shared Todo Core operation; no model call.') +
            ' For counts, quote result.stats.total, result.stats.pending and result.stats.done verbatim, with result.revision. Never count the todos list yourself. If stats is absent, report unavailable; do not estimate. Total includes cancelled items.',
            'inputSchema': {'type': 'object', 'additionalProperties': False,
                'properties': {'request_id': deepcopy(_ID), 'expected_revision': {'type': 'integer', 'minimum': 0},
                    'arguments': schema.model_json_schema()},
                'required': required_envelope},
            'annotations': {'readOnlyHint': action in _READS, 'destructiveHint': action == 'delete_todo',
                            'idempotentHint': True, 'openWorldHint': False}})
    return result


def failure(status):
    return {'ok': False, 'status': status, 'result': None, 'error': {'code': status}}


class GrokButlerAdapter:
    """Bind source=grok and forward a structured command without paraphrasing it."""
    def __init__(self, origin, token, *, transport=None, timeout=5.0):
        uri = urlsplit(origin)
        if (uri.scheme != 'http' or uri.hostname not in ('127.0.0.1', 'localhost', '::1')
                or uri.port is None or uri.port in (3001, 3101, 8000)
                or uri.username or uri.password or uri.path not in ('', '/') or uri.query or uri.fragment):
            raise ValueError('An isolated loopback Butler origin is required')
        if not isinstance(token, str) or not token or any(ch.isspace() for ch in token):
            raise ValueError('An injected Butler credential is required')
        self._endpoint = origin.rstrip('/') + '/v1/butler/commands'
        self._token = token
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False)

    def close(self):
        self._client.close()

    def call_tool(self, name, inputs):
        if not isinstance(name, str) or name not in _PUBLIC_ACTIONS:
            return failure('unknown_tool')
        if not isinstance(inputs, dict) or set(inputs) - {'request_id', 'expected_revision', 'arguments'}:
            return failure('validation_error')
        request_id = inputs.get('request_id')
        if not isinstance(request_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id) is None:
            return failure('validation_error')
        revision = inputs.get('expected_revision')
        if (name not in _READS and 'expected_revision' not in inputs
                or 'expected_revision' in inputs and (type(revision) is not int or revision < 0)):
            return failure('validation_error')
        arguments = inputs.get('arguments')
        if not isinstance(arguments, dict):
            return failure('validation_error')
        # Use the same schema as the Gateway; the Gateway remains the authority for state.
        command = {'source': 'grok', 'request_id': request_id, 'action': name, 'arguments': deepcopy(arguments)}
        if 'expected_revision' in inputs:
            command['expected_revision'] = revision
        try:
            command = Command.model_validate(command).model_dump(exclude_none=True)
        except ValidationError:
            return failure('validation_error')
        try:
            response = self._client.post(self._endpoint, json=command,
                headers={'Authorization': 'Bearer ' + self._token})
            if response.is_redirect:
                return failure('gateway_redirect_rejected')
            if len(response.content) > 1048576:
                return failure('gateway_invalid_response')
            payload = response.json()
            if (not isinstance(payload, dict) or type(payload.get('ok')) is not bool
                    or not isinstance(payload.get('status'), str) or not {'result', 'error'} <= set(payload)):
                return failure('gateway_invalid_response')
            if response.is_error and payload['ok']:
                return failure('gateway_invalid_response')
            return payload
        except (httpx.HTTPError, ValueError, TypeError):
            # Do not expose endpoint errors, Authorization headers or user intent in logs.
            return failure('gateway_unavailable')


