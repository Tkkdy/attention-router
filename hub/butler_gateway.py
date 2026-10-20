# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Authenticated deterministic Gateway; semantic resolution is an optional injected port.

Only shadow operations and an explicitly injected isolated Hub projection are exposed.
"""
import secrets
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from butler_models import Command, READS, BRIDGE_ACTIONS, TIBO_ACTIONS, INTERRUPT_ACTIONS
from todo_core import ButlerError

class ButlerGateway:
    def __init__(self, core, resolver=None, bridge=None, action_permissions=None, attention_port=None, activity_observer=None, interrupt_port=None):
        self.interrupt_port = interrupt_port
        self.attention_port = attention_port
        self.core, self.resolver, self.bridge = core, resolver, bridge
        self.action_permissions = {key: frozenset(value) for key, value in (action_permissions or {}).items()}

    def require_action(self, principal, action):
        allowed = self.action_permissions.get(principal)
        if (action in INTERRUPT_ACTIONS and allowed is None) or (allowed is not None and action not in allowed):
            raise ButlerError('action_forbidden', 403)

    def finish(self, result, action):
        if self.bridge is None:
            return result
        # Retry projection from the latest authoritative state, never roll back to a cached snapshot.
        latest = self.core.snapshot()
        projection = self.bridge.project(latest)
        result = {**result, 'bridge': projection}
        if action == 'get_dashboard_state' and projection['status'] == 'projected':
            result['dashboard'] = self.bridge.dashboard(latest)
        return result

    def require_bridge(self, action):
        if action in BRIDGE_ACTIONS and self.bridge is None:
            raise ButlerError('bridge_unavailable', 503)

    def execute(self, command, *, principal):
        command = Command.model_validate(command.model_dump())
        if principal not in {'deepseek', 'grok'} or command.source != principal:
            raise ButlerError('source_forbidden', 403)
        self.require_action(principal, command.action)
        self.require_bridge(command.action)
        if command.action in INTERRUPT_ACTIONS:
            if self.interrupt_port is None:
                raise ButlerError('interrupt_unavailable', 503)
            return self.interrupt_port(command)
        if command.action in TIBO_ACTIONS:
            if self.attention_port is None:
                raise ButlerError('attention_unavailable', 503)
            return self.attention_port(command)
        if command.action != 'resolve_intent':
            return self.finish(self.core.execute(command), command.action)
        cached = self.core.retry(command)
        if cached is not None:
            resolved_action = (cached.get('semantic') or {}).get('action')
            if resolved_action and resolved_action != 'semantic_noop':
                self.require_action(principal, resolved_action)
            return self.finish(cached, (cached.get('semantic') or {}).get('action', command.action))
        state = self.core.snapshot()
        if command.expected_revision != state['revision']:
            raise ButlerError('conflict', revision=state['revision'])
        if self.resolver is None:
            raise ButlerError('semantic_resolver_unavailable', 503)
        try:
            # Original expression, optional non-authoritative hint and business snapshot.
            resolved = self.resolver({**command.arguments, 'source': command.source,
                                      'request_id': command.request_id, 'state': state})
            if not isinstance(resolved, dict) or set(resolved) not in ({'action', 'arguments'}, {'action', 'arguments', 'semantic'}):
                raise ValueError('resolver must return one narrow action')
            semantic = resolved.get('semantic')
            if resolved['action'] == 'semantic_noop':
                if resolved['arguments']:
                    raise ValueError('noop cannot carry state changes')
                return self.finish(self.core.record_noop(command, semantic), command.action)
            action = Command.model_validate({**command.model_dump(), 'action': resolved['action'],
                                             'arguments': resolved['arguments']})
            if action.action == 'resolve_intent':
                raise ValueError('resolver cannot recursively request resolution')
        except ButlerError:
            raise
        except (ValueError, ValidationError):
            raise ButlerError('invalid_resolution', 422) from None
        except Exception:
            raise ButlerError('semantic_resolver_unavailable', 503) from None
        # Recheck revision transactionally after the model/network finishes. Never last-write-wins.
        self.require_action(principal, action.action)
        self.require_bridge(action.action)
        result = self.core.execute(action, audit_command=command, semantic=semantic)
        return self.finish(result, action.action)


def create_butler_app(core, tokens: dict[str, str], resolver=None, bridge=None, action_permissions=None, attention_port=None, activity_observer=None, interrupt_port=None):
    if not tokens or any(not isinstance(t, str) or len(t) < 32 or s not in {'deepseek', 'grok'}
                         for t, s in tokens.items()):
        raise ValueError('provider-bound credentials of at least 32 characters are required')
    credentials = dict(tokens)
    gateway = ButlerGateway(core, resolver, bridge, action_permissions, attention_port, interrupt_port=interrupt_port)
    app = FastAPI(title='Butler Shadow Gateway', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gateway = gateway
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '::1', 'testserver'])

    @app.middleware('http')
    async def authenticate(request: Request, call_next):
        auth = request.headers.get('authorization', '')
        principal = next((source for token, source in credentials.items()
                          if secrets.compare_digest(auth, 'Bearer ' + token)), None)
        if principal is None:
            return JSONResponse({'ok': False, 'status': 'unauthorized', 'result': None,
                                 'error': {'code': 'unauthorized'}}, status_code=401,
                                headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'})
        if request.headers.get('origin'):
            return JSONResponse({'ok': False, 'status': 'browser_origin_forbidden', 'result': None,
                                 'error': {'code': 'browser_origin_forbidden'}}, status_code=403)
        # Bound the body before framework parsing; do not log caller content or tokens.
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > 65536:
                return JSONResponse({'ok': False, 'status': 'request_too_large', 'result': None,
                                     'error': {'code': 'request_too_large'}}, status_code=413)
        request._body = bytes(payload)
        request.state.principal = principal
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ButlerError)
    async def failure(request, error):
        details = {'code': error.code}
        if error.revision is not None:
            details['current_revision'] = error.revision
        return JSONResponse({'ok': False, 'status': error.code, 'result': None, 'error': details},
                            status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({'ok': False, 'status': 'validation_error', 'result': None,
                             'error': {'code': 'validation_error'}}, status_code=422)

    @app.post('/v1/butler/commands')
    def execute(command: Command, request: Request):
        result = gateway.execute(command, principal=request.state.principal)
        if activity_observer:
            try:
                activity_observer(request.state.principal, command.action)
            except Exception:
                pass  # Observability must not turn a committed command into a failed request.
        return {'ok': True, 'status': 'ok', 'error': None, 'result': result}

    return app

