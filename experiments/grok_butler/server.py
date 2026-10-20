# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""D3 OAuth facade; forwards to the existing loopback Gateway, owns no Todo state."""
import json
import time
from typing import Annotated
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, StrictInt, create_model
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route

from experiments.oauth_spike.oauth import AuthorizationServer, Observations
from experiments.grok_butler.transport import ObservationMiddleware, SpikeTransportBoundary
from hub.grok_butler_adapter import tool_definitions
from hub.butler_models import SCHEMAS
from hub.grok_capabilities import actions_for, READ_ACTIONS, TIBO_ACTIONS, INTERRUPT_ACTIONS


def build_tool(definition, adapter, observations):
    name = definition['name']

    def invoke(request_id, arguments, expected_revision=None) -> CallToolResult:
        inputs = {'request_id': request_id, 'arguments': arguments.model_dump(exclude_unset=True)}
        if expected_revision is not None:
            inputs['expected_revision'] = expected_revision
        payload = adapter.call_tool(name, inputs)
        result = payload.get('result') or {}
        revision = result.get('revision') if isinstance(result, dict) else None
        observations.record('butler_tool_result', tool=name, ok=payload['ok'],
                            revision=revision if type(revision) is int else None)
        return CallToolResult(content=[TextContent(type='text', text=json.dumps(payload, ensure_ascii=False))],
                              structuredContent=payload, isError=not payload['ok'])

    tool = Tool.from_function(invoke, name=name, description=definition['description'],
        annotations=ToolAnnotations(read_only_hint=name in (READ_ACTIONS | {"get_tibo_attention"}),
            destructive_hint=False, idempotent_hint=True, open_world_hint=False))
    fields = dict(request_id=(Annotated[str, Field(strict=True, min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')], ...),
                  arguments=(SCHEMAS[name], ...))
    if name in (READ_ACTIONS | {"get_tibo_attention"}):
        fields['expected_revision'] = (Annotated[StrictInt, Field(ge=0)] | None, None)
    else:
        fields['expected_revision'] = (Annotated[StrictInt, Field(ge=0)], ...)
    model = create_model(name + '_input', __base__=ArgModelBase, **fields)
    model.model_config['extra'] = 'forbid'
    model.model_rebuild(force=True)
    tool.fn_metadata.arg_model = model
    tool.parameters = model.model_json_schema()
    return tool


def create_app(origin, adapter, *, owner_code, scope='butler:read', observations=None, clock=time.time, authorization=None, tibo_enabled=False, interrupt_enabled=False):
    uri = urlsplit(origin)
    if (uri.username or uri.password or uri.query or uri.fragment or uri.path not in ('', '/')
            or not uri.hostname or uri.port in (3001, 3101, 8000)
            or (uri.scheme != 'https' and not (uri.scheme == 'http'
                and uri.hostname in ('localhost', '127.0.0.1') and uri.port == 3103))):
        raise ValueError('use HTTPS origin or isolated loopback:3103')
    origin = origin.rstrip('/')
    allowed = actions_for(scope) | (TIBO_ACTIONS if tibo_enabled and scope == "butler:write" else set())
    allowed |= INTERRUPT_ACTIONS if interrupt_enabled and scope == 'butler:write' else set()
    observations = observations or Observations()
    if authorization is None:
        authorization = AuthorizationServer(origin, observations, clock, scope=scope, owner_code=owner_code)
    elif authorization.origin != origin or authorization.scope != scope:
        raise ValueError('authorization origin/scope must match resource server')
    tools = [build_tool(item, adapter, observations) for item in tool_definitions() if item['name'] in allowed]
    server = MCPServer(name='grokbot-shared-shadow-butler', version='d3-interrupt-1', tools=tools, subscriptions=False,
        instructions=('Shared shadow Todo tools. Read get_context before writes and use its revision. '
            'Use a unique request_id per operation; reuse it only for an identical retry. '
            'Never automatically overwrite on conflict. Structured calls go directly to Todo Core. '
            'For raw or ambiguous intent use resolve_intent with the exact original user message. '
            'This connector cannot access production Todo, direct device commands, shell or files.'
            + (' The owner delegates autonomous Interrupt timing and English content through show_interrupt. No per-message reminder request is needed. Never auto-ACK; Hub acceptance is not proof of physical display.' if interrupt_enabled and scope == 'butler:write' else '')),
        log_level='CRITICAL', token_verifier=authorization,
        auth=AuthSettings(issuer_url=origin, resource_server_url=origin + '/mcp',
                         required_scopes=[scope], validate_token_resource=True))
    app = server.streamable_http_app(host='127.0.0.1', stateless_http=True, json_response=True,
        max_request_body_size=65536,
        transport_security=TransportSecuritySettings(
            allowed_hosts=['127.0.0.1:3103', 'localhost:3103', uri.netloc],
            allowed_origins=['http://127.0.0.1:3103', 'http://localhost:3103', origin]))
    for route in app.routes:
        if getattr(route, 'path', None) == '/mcp':
            route.app = SpikeTransportBoundary(route.app, origin, required_scope=scope)
    app.routes.extend([
        Route('/.well-known/oauth-protected-resource', authorization.resource_metadata),
        Route('/.well-known/oauth-authorization-server', authorization.metadata),
        Route('/register', authorization.register, methods=['POST']),
        Route('/authorize', authorization.authorize, methods=['GET', 'POST']),
        Route('/consent', authorization.consent, methods=['POST']),
        Route('/token', authorization.token, methods=['POST']),
    ])
    app.state.mcp_server = server
    app.state.authorization = authorization
    if hasattr(authorization, 'revoke'):
        app.routes.append(Route('/revoke', authorization.revoke, methods=['POST']))
    app.state.observations = observations
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', uri.hostname])
    app.add_middleware(ObservationMiddleware, observations=observations)
    return app


def verify_tool_discovery(app, *, interrupt_enabled=False):
    """Check the real SDK registry, not only the configured action allowlist."""
    import asyncio
    names = sorted(tool.name for tool in asyncio.run(app.state.mcp_server.list_tools()))
    if ('show_interrupt' in names) != interrupt_enabled:
        raise ValueError('Interrupt capability does not match actual MCP tools/list')
    return names


def main():
    import argparse
    import getpass
    import logging
    import uvicorn
    from hub.grok_butler_adapter import GrokButlerAdapter
    parser = argparse.ArgumentParser(description='Experimental loopback OAuth/MCP facade for your Gateway')
    parser.add_argument('--scope', choices=('butler:read', 'butler:write'), default='butler:read')
    parser.add_argument('--allow-autonomous-interrupts', action='store_true')
    args = parser.parse_args()
    if args.allow_autonomous_interrupts and args.scope != 'butler:write':
        parser.error('Interrupt requires explicit butler:write scope')
    # OAuth URLs/callbacks and errors may contain credentials; no access/error dumps.
    logging.disable(logging.CRITICAL)
    key = getpass.getpass('Provider-bound Grok Gateway token: ')
    owner = getpass.getpass('Your new owner pairing code (32+ random ASCII characters): ')
    if any(len(value) < 32 or not value.isascii() or any(c.isspace() for c in value)
           for value in (key, owner)) or key == owner:
        parser.error('use distinct 32+ ASCII non-whitespace credentials')
    adapter = GrokButlerAdapter('http://127.0.0.1:3102', key)
    try:
        application = create_app('http://127.0.0.1:3103', adapter, owner_code=owner,
            scope=args.scope, interrupt_enabled=args.allow_autonomous_interrupts)
        names = verify_tool_discovery(application, interrupt_enabled=args.allow_autonomous_interrupts)
        print('Actual MCP tools/list: ' + ', '.join(names), flush=True)
        uvicorn.run(application, host='127.0.0.1', port=3103,
                    access_log=False, log_level='critical', proxy_headers=False)
    finally:
        adapter.close()


if __name__ == '__main__':
    main()
