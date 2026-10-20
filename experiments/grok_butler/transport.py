# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Existing OAuth/MCP request boundaries, extracted without the ping runtime."""
import json
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from starlette.responses import JSONResponse

class SpikeTransportBoundary:
    """Normalize SDK auth failures; keep authentication before MCP/session handling."""
    def __init__(self, app, origin, required_scope='ping'):
        self.app = app
        self.required_scope = required_scope
        self.metadata = origin + '/.well-known/oauth-protected-resource/mcp'

    async def __call__(self, scope, receive, send):
        # Streamable HTTP permits 405 for the optional standalone GET SSE stream.
        user = scope.get('user')
        if scope['method'] == 'GET' and isinstance(user, AuthenticatedUser) and self.required_scope in user.scopes:
            await JSONResponse({'error': 'standalone_sse_not_supported'}, status_code=405,
                headers={'Allow': 'POST, DELETE'})(scope, receive, send)
            return
        supplied = any(key.lower() == b'authorization' for key, _ in scope.get('headers', []))
        replaced = False
        async def normalize(message):
            nonlocal replaced
            if message['type'] == 'http.response.start' and message['status'] == 401:
                replaced = True
                challenge = f'Bearer resource_metadata="{self.metadata}", scope="{self.required_scope}"'
                body = {'error': 'authentication_required'}
                if supplied:
                    challenge += ', error="invalid_token"'
                    body = {'error': 'invalid_token'}
                await JSONResponse(body, status_code=401,
                    headers={'WWW-Authenticate': challenge, 'Cache-Control': 'no-store'})(scope, receive, send)
            elif not replaced:
                await send(message)
        await self.app(scope, receive, normalize)


class ObservationMiddleware:
    def __init__(self, app, observations):
        self.app = app
        self.observations = observations

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        known = ('/mcp', '/authorize', '/consent', '/token', '/register',
            '/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource',
            '/.well-known/oauth-authorization-server', '/.well-known/openid-configuration')
        path = scope['path'] if scope['path'] in known else '[other]'
        self.observations.record('request', method=scope['method'], endpoint=path)
        body = b''
        if scope['method'] == 'POST':
            while True:
                part = await receive()
                if part['type'] == 'http.disconnect':
                    return
                body += part.get('body', b'')
                if len(body) > 65536:
                    return await JSONResponse({'error': 'request_too_large'}, status_code=413)(scope, receive, send)
                if not part.get('more_body'):
                    break
        if path == '/mcp' and body:
            try:
                data = json.loads(body)
                method = data.get('method') if isinstance(data, dict) else None
                if method in ('initialize', 'notifications/initialized', 'tools/list', 'tools/call'):
                    self.observations.record('mcp_request', method=method,
                        ping_requested=method == 'tools/call' and isinstance(data.get('params'), dict) and data['params'].get('name') == 'ping')
            except (ValueError, UnicodeError):
                pass
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered and scope['method'] == 'POST':
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()
        started = False
        async def observed_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
                self.observations.record('response', endpoint=path, status=message['status'])
            await send(message)
        try:
            await self.app(scope, replay, observed_send)
        except Exception:
            # Deliberately no repr/traceback/request dump in this experimental protocol log.
            self.observations.record('controlled_error', endpoint=path)
            if not started:
                await JSONResponse({'error': 'server_error'}, status_code=500)(scope, replay, observed_send)

