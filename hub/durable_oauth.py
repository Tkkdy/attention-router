# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Shadow OAuth persistence: hashed bearer tokens, rotation, family revocation.

Authorization tickets/codes deliberately remain ephemeral; completed grants and
public client registrations survive restart. No raw token is written to disk.
"""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from mcp.server.auth.provider import AccessToken
from starlette.responses import JSONResponse
from experiments.oauth_spike.oauth import AuthorizationServer


def digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


class OAuthStore:
    def __init__(self, path, origin, scope):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY, origin TEXT, scope TEXT)')
            row = db.execute('SELECT origin,scope FROM binding WHERE id=1').fetchone()
            if row and tuple(row) != (origin, scope):
                raise ValueError('OAuth store is bound to another origin/scope; use a separate store')
            db.execute('INSERT OR IGNORE INTO binding VALUES(1,?,?)', (origin, scope))
            db.execute('CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, redirects TEXT, refresh INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS families (id TEXT PRIMARY KEY, client TEXT, expires REAL, revoked INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, kind TEXT, family TEXT, expires REAL, consumed INTEGER)')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                db.row_factory = sqlite3.Row
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def clients(self):
        with self.transaction() as db:
            return {row['id']: json.loads(row['redirects']) for row in db.execute('SELECT * FROM clients')}

    def register(self, client, redirects, refresh):
        with self.transaction() as db:
            db.execute('INSERT INTO clients VALUES(?,?,?)', (client, json.dumps(redirects), int(refresh)))

    def allows_refresh(self, client):
        with self.transaction() as db:
            row = db.execute('SELECT refresh FROM clients WHERE id=?', (client,)).fetchone()
            return bool(row and row['refresh'])

    @staticmethod
    def insert_pair(db, family, now, access_ttl, expires, refresh):
        access = secrets.token_urlsafe(32)
        db.execute('INSERT INTO tokens VALUES(?,?,?,?,0)', (digest(access), 'access', family, min(now + access_ttl, expires)))
        renewal = None
        if refresh:
            renewal = secrets.token_urlsafe(48)
            db.execute('INSERT INTO tokens VALUES(?,?,?,?,0)', (digest(renewal), 'refresh', family, expires))
        return access, renewal

    def issue(self, client, now, access_ttl, refresh_ttl, refresh):
        with self.transaction() as db:
            family = secrets.token_hex(16)
            expires = now + (refresh_ttl if refresh else access_ttl)
            db.execute('INSERT INTO families VALUES(?,?,?,0)', (family, client, expires))
            return self.insert_pair(db, family, now, access_ttl, expires, refresh)

    def rotate(self, token, client, now, access_ttl):
        with self.transaction() as db:
            row = db.execute('SELECT t.*,f.client,f.revoked,f.expires AS family_expires FROM tokens t JOIN families f ON f.id=t.family WHERE t.hash=? AND t.kind=?', (digest(token), 'refresh')).fetchone()
            if not row or row['client'] != client or row['revoked'] or row['expires'] <= now:
                return None, 'invalid_grant'
            if row['consumed']:
                db.execute('UPDATE families SET revoked=1 WHERE id=?', (row['family'],))
                return None, 'refresh_replay'
            db.execute('UPDATE tokens SET consumed=1 WHERE hash=?', (digest(token),))
            # A family's absolute expiry never slides forward during rotation.
            pair = self.insert_pair(db, row['family'], now, access_ttl, row['family_expires'], True)
            return pair, 'rotated'

    def verify(self, token, now):
        with self.transaction() as db:
            row = db.execute('SELECT f.client,t.expires FROM tokens t JOIN families f ON f.id=t.family WHERE t.hash=? AND t.kind=? AND t.expires>? AND f.expires>? AND f.revoked=0', (digest(token), 'access', now, now)).fetchone()
            return dict(row) if row else None

    def revoke(self, token, client):
        with self.transaction() as db:
            db.execute('UPDATE families SET revoked=1 WHERE client=? AND id IN (SELECT family FROM tokens WHERE hash=?)', (client, digest(token)))


class DurableAuthorizationServer(AuthorizationServer):
    def __init__(self, origin, observations, *, scope, owner_code, path, clock=time.time,
                 access_ttl=600, refresh_ttl=7 * 86400):
        super().__init__(origin, observations, clock, scope=scope, owner_code=owner_code)
        if not 30 <= access_ttl <= 3600 or not access_ttl < refresh_ttl <= 90 * 86400:
            raise ValueError('finite bounded token lifetimes required')
        self.store = OAuthStore(path, origin, scope)
        self.clients = self.store.clients()
        self.access_ttl, self.refresh_ttl = access_ttl, refresh_ttl

    async def metadata(self, request):
        response = await super().metadata(request)
        data = json.loads(response.body)
        data.update(grant_types_supported=['authorization_code', 'refresh_token'],
                    revocation_endpoint=self.origin + '/revoke', revocation_endpoint_auth_methods_supported=['none'])
        return JSONResponse(data)

    async def register(self, request):
        response = await super().register(request)
        if response.status_code != 201:
            return response
        data = json.loads(response.body)
        wants_refresh = 'refresh_token' in (await request.json()).get('grant_types', ['authorization_code'])
        self.store.register(data['client_id'], data['redirect_uris'], wants_refresh)
        if wants_refresh:
            data['grant_types'].append('refresh_token')
        self.observations.record('durable_registration', client_id=data['client_id'], refresh_enabled=wants_refresh)
        return JSONResponse(data, status_code=201, headers={'Cache-Control': 'no-store'})

    async def authorize(self, request):
        response = await super().authorize(request)
        if response.status_code == 200:
            # Explicit disclosure: consent can permit refresh beyond one access token.
            text = response.body.decode('utf-8').replace('</h1>', '</h1><p>Access expires after '
                + str(self.access_ttl) + ' seconds. If requested by this client, rotating refresh authorization lasts at most '
                + str(self.refresh_ttl // 86400) + ' days and can be revoked locally.</p>', 1)
            from starlette.responses import HTMLResponse
            headers = dict(response.headers)
            headers.pop('content-length', None)
            return HTMLResponse(text, headers=headers)
        return response

    def issued_response(self, pair, client, *, refreshed=False):
        access, renewal = pair
        entry = self.store.verify(access, self.clock())
        ttl = max(0, int(entry['expires'] - self.clock()))
        data = {'access_token': access, 'token_type': 'Bearer', 'expires_in': ttl, 'scope': self.scope}
        if renewal:
            data['refresh_token'] = renewal
        self.observations.record('durable_token_issued', client_id=client, scope=self.scope,
            expires_in=ttl, refresh_present=renewal is not None, refreshed=refreshed)
        return JSONResponse(data, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})

    async def token(self, request):
        self.prune()
        try:
            data = await self.params(request)
        except (ValueError, UnicodeError):
            return self.error('invalid_request')
        client = data.get('client_id')
        self.observations.protocol('durable_token_exchange', data,
            client_id=client if client in self.clients else '[unregistered]')
        if client not in self.clients or request.headers.get('authorization') or data.get('client_secret'):
            return self.error('invalid_client')
        if data.get('resource', self.resource) != self.resource or data.get('audience', self.resource) != self.resource:
            return self.error('invalid_target')
        if data.get('scope', self.scope) != self.scope:
            return self.error('invalid_scope')
        if data.get('grant_type') == 'refresh_token':
            raw = data.get('refresh_token', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{64}', raw):
                return self.error('invalid_grant')
            pair, outcome = self.store.rotate(raw, client, self.clock(), self.access_ttl)
            self.observations.record('refresh_result', client_id=client, outcome=outcome)
            return self.issued_response(pair, client, refreshed=True) if pair else self.error('invalid_grant')
        if data.get('grant_type') != 'authorization_code':
            return self.error('unsupported_grant_type')
        code = self.codes.get(data.get('code'))
        if code is None or code['client_id'] != client or code['redirect_uri'] != data.get('redirect_uri'):
            return self.error('invalid_grant')
        verifier = data.get('code_verifier', '')
        if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
            return self.error('invalid_grant')
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        if not hmac.compare_digest(challenge, code['code_challenge']):
            return self.error('invalid_grant')
        del self.codes[data['code']]
        pair = self.store.issue(client, self.clock(), self.access_ttl, self.refresh_ttl, self.store.allows_refresh(client))
        return self.issued_response(pair, client)

    async def verify_token(self, token):
        entry = self.store.verify(token, self.clock()) if re.fullmatch(r'[A-Za-z0-9_-]{43}', token) else None
        self.observations.record('bearer_validation', accepted=entry is not None)
        return AccessToken(token=token, client_id=entry['client'], scopes=[self.scope],
            expires_at=int(entry['expires']), resource=self.resource) if entry else None

    async def revoke(self, request):
        try:
            data = await self.params(request)
        except (ValueError, UnicodeError):
            return self.error('invalid_request')
        client = data.get('client_id')
        if client not in self.clients or request.headers.get('authorization') or data.get('client_secret'):
            return self.error('invalid_client')
        self.store.revoke(data.get('token', ''), client)
        self.observations.record('grant_revoked', client_id=client)
        return JSONResponse({}, headers={'Cache-Control': 'no-store'})
