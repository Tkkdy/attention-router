# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Ephemeral public-client authorization server; no production imports or credentials."""
import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from mcp.server.auth.provider import AccessToken
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

CODE_TTL = 120
TOKEN_TTL = 600
CONSENT_TTL = 900


def safe_uri(value):
    """Log callback routing, never query/fragment/userinfo (possibly credential-bearing)."""
    try:
        uri = urlsplit(value)
        host = uri.hostname or ''
        port = f':{uri.port}' if uri.port else ''
        # Custom scheme authority can have opaque routing; hostname remains nonsecret.
        return urlunsplit((uri.scheme, host + port, uri.path, '', ''))
    except (ValueError, TypeError):
        return '[invalid URI]'


def uri_kind(value):
    try:
        uri = urlsplit(value)
        if uri.hostname in ('localhost', '127.0.0.1', '::1'):
            return 'localhost'
        return 'https' if uri.scheme == 'https' else 'custom_scheme'
    except ValueError:
        return 'invalid'


class Observations:
    """Only whitelisted booleans/enums and sanitized routing metadata enter JSONL."""
    def __init__(self, sink=None):
        self.events = []
        self.sink = sink

    def record(self, event, **fields):
        entry = dict(sequence=len(self.events) + 1, time=int(time.time()), event=event, **fields)
        self.events.append(entry)
        if self.sink:
            self.sink(json.dumps(entry, ensure_ascii=True))

    def protocol(self, event, params, **fields):
        redirects = params.get('redirect_uris', [])
        if isinstance(params.get('redirect_uri'), str):
            redirects = [params['redirect_uri']]
        if not isinstance(redirects, list):
            redirects = []
        self.record(event,
            redirect_uris=[safe_uri(x) for x in redirects if isinstance(x, str)],
            redirect_uri_kinds=[uri_kind(x) for x in redirects if isinstance(x, str)],
            # Only server-issued client IDs can be logged verbatim by callers below.
            response_type=params.get('response_type') if params.get('response_type') in ('code', 'token') else 'other_or_absent',
            grant_type=params.get('grant_type') if params.get('grant_type') in ('authorization_code', 'refresh_token') else 'other_or_absent',
            grant_types=[x for x in params.get('grant_types', []) if x in ('authorization_code', 'refresh_token')] if isinstance(params.get('grant_types'), list) else [],
            code_challenge_present=bool(params.get('code_challenge')),
            code_challenge_method='S256' if params.get('code_challenge_method') == 'S256' else 'other_or_absent',
            code_verifier_present=bool(params.get('code_verifier')),
            client_secret_present=bool(params.get('client_secret')),
            token_endpoint_auth_method=params.get('token_endpoint_auth_method') if params.get('token_endpoint_auth_method') in ('none', 'client_secret_post', 'client_secret_basic') else 'other_or_absent',
            resource=safe_uri(params['resource']) if isinstance(params.get('resource'), str) else None,
            audience=safe_uri(params['audience']) if isinstance(params.get('audience'), str) else None,
            **fields)


class AuthorizationServer:
    def __init__(self, origin, observations, clock=time.time, *, scope='ping', owner_code=None):
        if scope not in {'ping', 'butler:read', 'butler:write'}:
            raise ValueError('unsupported scope')
        if scope != 'ping' and (not isinstance(owner_code, str) or not 32 <= len(owner_code) <= 256):
            raise ValueError('business consent requires a local owner pairing code')
        self.scope, self._owner_code = scope, owner_code
        self.origin = origin
        self.resource = origin + '/mcp'
        self.observations = observations
        self.clock = clock
        self.clients = {}
        self.pending = {}
        self.codes = {}
        self.tokens = {}

    def prune(self):
        now = self.clock()
        for mapping in (self.pending, self.codes, self.tokens):
            for key in list(mapping):
                if mapping[key]['expires'] <= now:
                    del mapping[key]

    def error(self, error, status=400):
        return JSONResponse({'error': error}, status_code=status,
            headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})

    async def params(self, request):
        if request.method == 'GET':
            pairs = request.query_params.multi_items()
        else:
            if not request.headers.get('content-type', '').startswith('application/x-www-form-urlencoded'):
                raise ValueError('invalid_request')
            parsed = parse_qs((await request.body()).decode('utf-8'), keep_blank_values=True)
            pairs = [(key, value) for key, values in parsed.items() for value in values]
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('invalid_request')
            result[key] = value
        return result

    async def metadata(self, request):
        return JSONResponse({
            'issuer': self.origin,
            'authorization_endpoint': self.origin + '/authorize',
            'token_endpoint': self.origin + '/token',
            'registration_endpoint': self.origin + '/register',
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code'],
            'token_endpoint_auth_methods_supported': ['none'],
            'code_challenge_methods_supported': ['S256'],
            'scopes_supported': [self.scope],
        })

    async def resource_metadata(self, request):
        return JSONResponse({'resource': self.resource, 'authorization_servers': [self.origin],
            'scopes_supported': [self.scope], 'bearer_methods_supported': ['header']})

    async def register(self, request):
        try:
            data = await request.json()
            if not isinstance(data, dict):
                return self.error('invalid_client_metadata')
            self.observations.protocol('registration_attempt', data)
            redirects = data.get('redirect_uris')
            if not isinstance(redirects, list) or not redirects or len(redirects) > 10:
                return self.error('invalid_redirect_uri')
            for value in redirects:
                if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
                    return self.error('invalid_redirect_uri')
                uri = urlsplit(value)
                if not uri.scheme or uri.fragment or uri.username or uri.password:
                    return self.error('invalid_redirect_uri')
                if uri.scheme in ('javascript', 'data', 'file'):
                    return self.error('invalid_redirect_uri')
                if uri.scheme == 'http' and uri.hostname not in ('localhost', '127.0.0.1', '::1'):
                    return self.error('invalid_redirect_uri')
                if uri.scheme in ('http', 'https') and not uri.hostname:
                    return self.error('invalid_redirect_uri')
            # Absence means this spike's sole supported public client method, never a secret.
            if data.get('token_endpoint_auth_method', 'none') != 'none':
                return self.error('invalid_client_metadata')
            requested_grants = data.get('grant_types', ['authorization_code'])
            if (not isinstance(requested_grants, list) or 'authorization_code' not in requested_grants
                    or any(g not in ('authorization_code', 'refresh_token') for g in requested_grants)
                    or data.get('response_types', ['code']) != ['code']):
                self.observations.record('registration_rejected', reason='unsupported_grant_or_response_type')
                return self.error('invalid_client_metadata')
            # Negotiate only the supported grant, explicitly returned in the DCR response.
            # This does not enable refresh tokens or expand the ping capability.
            self.observations.record('registration_grants', refresh_requested='refresh_token' in requested_grants, granted=['authorization_code'])
            if data.get('scope', self.scope) != self.scope:
                return self.error('invalid_client_metadata')
            if len(self.clients) >= 1000:
                return self.error('temporarily_unavailable', 503)
            client_id = 'spike_' + secrets.token_urlsafe(16)
            # Exact submitted strings; no callback normalization or replacement.
            self.clients[client_id] = list(redirects)
            self.observations.record('registered', client_id=client_id)
            return JSONResponse({'client_id': client_id, 'client_id_issued_at': int(self.clock()),
                'redirect_uris': redirects, 'token_endpoint_auth_method': 'none',
                'grant_types': ['authorization_code'], 'response_types': ['code'], 'scope': self.scope},
                status_code=201, headers={'Cache-Control': 'no-store'})
        except (ValueError, UnicodeError, TypeError):
            return self.error('invalid_client_metadata')

    async def authorize(self, request):
        self.prune()
        try:
            data = await self.params(request)
        except (ValueError, UnicodeError):
            return self.error('invalid_request')
        client = data.get('client_id')
        known = client in self.clients
        self.observations.protocol('authorization_attempt', data,
            client_id=client if known else (safe_uri(client) if isinstance(client, str) and client.startswith('https://') else '[unregistered]'),
            registration_mode='dynamic_registration' if known else 'unregistered_client', registered_client=known)
        if not known:
            return self.error('invalid_client')
        if data.get('redirect_uri') not in self.clients[client]:
            return self.error('invalid_redirect_uri')
        if data.get('response_type') != 'code':
            return self.error('unsupported_response_type')
        if data.get('code_challenge_method') != 'S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43}', data.get('code_challenge', '')):
            return self.error('invalid_request')
        if data.get('scope', self.scope) != self.scope:
            return self.error('invalid_scope')
        if data.get('resource', self.resource) != self.resource or data.get('audience', self.resource) != self.resource:
            return self.error('invalid_target')
        if len(self.pending) >= 1000:
            return self.error('temporarily_unavailable', 503)
        ticket = secrets.token_urlsafe(32)
        self.pending[ticket] = dict(data, expires=self.clock() + CONSENT_TTL)
        # Server-side ticket holds all flow parameters. No code on GET, no auto-approval.
        title = 'GrokBot OAuth Compatibility Test' if self.scope == 'ping' else 'GrokBot Shared Shadow Todo'
        permission = ('Only permits the test ping tool for 10 minutes.' if self.scope == 'ping'
            else 'Read shared shadow Todo and context for 10 minutes.' if self.scope == 'butler:read'
            else 'Read, create, update, complete, reorder shared shadow Todo; set current item, context and suggestions for 10 minutes. Ambiguous requests use the shared Resolver.')
        pairing = ('<label>Local owner pairing code <input type="password" name="owner_code" required maxlength="256" autocomplete="off"></label>'
            if self._owner_code is not None else '')
        page = (f'<!doctype html><meta charset="utf-8"><title>{title}</title>'
            f'<h1>{title}</h1><p>{permission}</p>'
            '<p>This approval page expires after 15 minutes. Approval is never automatic.</p>'
            f'<p>Client: {html.escape(client)}</p><p>Callback: {html.escape(safe_uri(data["redirect_uri"]))}</p>'
            '<form method="post" action="/consent">'
            f'<input type="hidden" name="ticket" value="{ticket}">'
            f'{pairing}'
            '<button name="decision" value="allow">Allow</button> '
            '<button name="decision" value="deny" formnovalidate>Deny</button></form>')
        # Chromium applies form-action to the post-consent callback redirect too.
        # Permit only this validated callback destination; never interpolate its query.
        callback_uri = urlsplit(data['redirect_uri'])
        callback_source = (quote(urlunsplit((callback_uri.scheme, callback_uri.netloc,
            callback_uri.path, '', '')), safe=':/[]%') if callback_uri.netloc
            else callback_uri.scheme + ':')
        # Cursor's registered www callback redirects to its canonical host.
        # Allow that observed destination only for this exact HTTPS callback;
        # OAuth redirect binding and token exchange still use the registered URI.
        if (callback_uri.scheme == 'https'
                and callback_uri.netloc == 'www.cursor.com'
                and callback_uri.path == '/agents/mcp/oauth/callback'):
            callback_source += ' https://cursor.com/agents/mcp/oauth/callback'
        return HTMLResponse(page, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'strict-origin',
            'Content-Security-Policy': f"default-src 'none'; form-action 'self' {callback_source}; frame-ancestors 'none'; base-uri 'none'",
            'X-Frame-Options': 'DENY'})

    def callback(self, data, **fields):
        uri = urlsplit(data['redirect_uri'])
        query = uri.query + ('&' if uri.query else '') + urlencode(dict(fields, **({'state': data['state']} if 'state' in data else {})))
        target = urlunsplit((uri.scheme, uri.netloc, uri.path, query, ''))
        # Chromium blocks this client's www -> canonical redirect during form
        # submission even with both destinations allowed. Finish the POST locally
        # and let an explicit link perform ordinary navigation to the exact URI.
        if (uri.scheme == 'https' and uri.netloc == 'www.cursor.com'
                and uri.path == '/agents/mcp/oauth/callback'):
            self.observations.record('callback_delivery', mode='manual_link')
            page = ('<!doctype html><meta charset="utf-8"><title>Return to GrokBot</title>'
                '<h1>Consent recorded</h1><p>Continue to return the result to GrokBot.</p>'
                f'<a rel="noreferrer" href="{html.escape(target, quote=True)}">Continue to GrokBot</a>'
                '<p>If the connection has expired, start a new connection in GrokBot.</p>')
            return HTMLResponse(page, headers={'Cache-Control': 'no-store',
                'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
                'Content-Security-Policy': "default-src 'none'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"})
        return RedirectResponse(target, status_code=303,
            headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})

    async def consent(self, request):
        origin = request.headers.get('origin')
        content_type = request.headers.get('content-type', '').split(';', 1)[0].lower()
        origin_kind = ('absent' if origin is None else 'same_origin' if origin == self.origin
            else 'opaque_null' if origin == 'null' else 'other')
        try:
            data = await self.params(request)
        except (ValueError, UnicodeError):
            self.observations.record('consent_rejected', reason='invalid_form',
                content_type='urlencoded' if content_type == 'application/x-www-form-urlencoded' else 'other', origin_kind=origin_kind)
            return self.error('invalid_request')
        pending = self.pending.get(data.get('ticket'))
        fields = sorted(name if name in ('ticket', 'decision', 'owner_code') else '[other]' for name in data)
        facts = dict(method=request.method, content_type='application/x-www-form-urlencoded' if content_type == 'application/x-www-form-urlencoded' else 'other',
            form_fields=fields, button_name='decision' if 'decision' in data else None,
            button_value=data.get('decision') if data.get('decision') in ('allow', 'deny') else 'other_or_absent',
            origin_kind=origin_kind, pending_identifier_present=bool(data.get('ticket')), pending_found=pending is not None,
            pending_expired=pending is not None and pending['expires'] <= self.clock())
        if pending is not None:
            facts.update(client_matches=pending['client_id'] in self.clients,
                redirect_matches=pending['redirect_uri'] in self.clients.get(pending['client_id'], []),
                scope_matches=pending.get('scope', self.scope) == self.scope, state_present='state' in pending,
                pkce_challenge_restored=bool(pending.get('code_challenge')),
                pkce_method_s256=pending.get('code_challenge_method') == 'S256')
        self.observations.record('consent_attempt', **facts)
        if origin not in (None, self.origin):
            self.observations.record('consent_rejected', reason='origin_mismatch')
            return self.error('invalid_request')
        if data.get('decision') not in ('allow', 'deny'):
            self.observations.record('consent_rejected', reason='invalid_decision')
            return self.error('invalid_request')
        if pending is None:
            self.observations.record('consent_rejected', reason='pending_missing_or_pruned')
            return self.error('invalid_request')
        if data.get('decision') == 'allow' and self._owner_code is not None:
            supplied = data.get('owner_code', '')
            if len(supplied) > 256 or not hmac.compare_digest(supplied.encode('utf-8'), self._owner_code.encode('utf-8')):
                self.observations.record('consent_rejected', reason='owner_pairing_required')
                return self.error('access_denied', 403)
        if not all(facts[key] for key in ('client_matches', 'redirect_matches', 'scope_matches', 'pkce_challenge_restored', 'pkce_method_s256')):
            self.observations.record('consent_rejected', reason='pending_binding_invalid')
            return self.error('invalid_request')
        del self.pending[data['ticket']]
        if facts['pending_expired']:
            # An expired request is never approved. A verified callback receives OAuth error + state.
            self.observations.record('consent_rejected', reason='pending_expired', callback_redirect=True)
            return self.callback(pending, error='access_denied')
        decision = data['decision']
        self.observations.record('consent', decision=decision, client_id=pending['client_id'])
        if decision == 'deny':
            self.observations.record('consent_redirect', code_issued=False, callback_redirect=True)
            return self.callback(pending, error='access_denied')
        code = secrets.token_urlsafe(32)
        self.codes[code] = dict(pending, expires=self.clock() + CODE_TTL)
        self.observations.record('consent_redirect', code_issued=True, callback_redirect=True)
        return self.callback(pending, code=code)

    async def token(self, request):
        self.prune()
        try:
            data = await self.params(request)
        except (ValueError, UnicodeError):
            return self.error('invalid_request')
        client = data.get('client_id')
        self.observations.protocol('token_exchange', data,
            client_id=client if client in self.clients else '[unregistered]',
            authorization_header_present=bool(request.headers.get('authorization')))
        if data.get('grant_type') != 'authorization_code':
            return self.error('unsupported_grant_type')
        if request.headers.get('authorization') or data.get('client_secret'):
            return self.error('invalid_client')
        code = self.codes.get(data.get('code'))
        if code is None or code['client_id'] != client or code['redirect_uri'] != data.get('redirect_uri'):
            return self.error('invalid_grant')
        if data.get('resource', self.resource) != self.resource or data.get('audience', self.resource) != self.resource:
            return self.error('invalid_target')
        verifier = data.get('code_verifier', '')
        if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
            return self.error('invalid_grant')
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        if not hmac.compare_digest(challenge, code['code_challenge']):
            return self.error('invalid_grant')
        # No await between validate/consume/mint: atomic within this single-process event loop.
        del self.codes[data['code']]
        token = secrets.token_urlsafe(32)
        self.tokens[token] = dict(client_id=client, expires=self.clock() + TOKEN_TTL)
        self.observations.record('token_issued', client_id=client, scope=self.scope, expires_in=TOKEN_TTL)
        return JSONResponse({'access_token': token, 'token_type': 'Bearer', 'expires_in': TOKEN_TTL, 'scope': self.scope},
            headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})

    async def verify_token(self, token):
        self.prune()
        entry = self.tokens.get(token)
        self.observations.record('bearer_validation', accepted=entry is not None)
        if entry is None:
            return None
        return AccessToken(token=token, client_id=entry['client_id'], scopes=[self.scope],
            expires_at=int(entry['expires']), resource=self.resource)
