# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Fail-closed HTTP Bearer authentication and Windows CurrentUser DPAPI storage."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
import re
import secrets
import sys
import os
import tempfile
import time

DEFAULT_CREDENTIAL = Path(__file__).resolve().parents[1] / ".build" / "mcp-auth" / "token.dpapi"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class CredentialError(ValueError):
    pass


def validate_token(token):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise CredentialError("MCP credential is missing or invalid; service remains closed.")
    return token


def _dpapi(data, *, protect):
    if sys.platform != "win32":
        raise CredentialError("Windows CurrentUser DPAPI is required.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        # UI_FORBIDDEN only; never LOCAL_MACHINE (which would allow other users).
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise CredentialError("MCP credential protection failed; service remains closed.")
        return ctypes.string_at(result.data, result.size)
    finally:
        if result.data:
            ctypes.memset(result.data, 0, result.size)
            kernel.LocalFree(result.data)
        ctypes.memset(buffer, 0, len(data))


def load_credential(path=DEFAULT_CREDENTIAL):
    try:
        path = Path(path)
        with path.open("rb") as file:
            ciphertext = file.read(16385)
        if not ciphertext or len(ciphertext) > 16384:
            raise CredentialError("Invalid credential file.")
        return validate_token(_dpapi(ciphertext, protect=False).decode("ascii"))
    except Exception:
        raise CredentialError("MCP credential unavailable for this Windows user; service remains closed.") from None


def provision_credential(path=DEFAULT_CREDENTIAL):
    path = Path(path)
    if path.exists():
        load_credential(path)  # Validate, never overwrite or silently rotate.
        return
    ciphertext = _dpapi(secrets.token_urlsafe(32).encode("ascii"), protect=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(ciphertext)


def rotate_credential(path=DEFAULT_CREDENTIAL):
    path = Path(path)
    load_credential(path)  # Rotation requires a valid existing credential.
    ciphertext = _dpapi(secrets.token_urlsafe(32).encode("ascii"), protect=True)
    fd, temporary = tempfile.mkstemp(prefix=".token-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(ciphertext); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


async def http_error(send, code, status, rpc_id=None, retry_after=None):
    headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
    if status == 401: headers.append((b"www-authenticate", b'Bearer realm="attention-mcp"'))
    if retry_after is not None: headers.append((b"retry-after", str(retry_after).encode("ascii")))
    import json
    body = {"jsonrpc":"2.0", "id":rpc_id, "error":{"code":-32001,
            "message":code, "data":{"code":code, "http_status":status}}}
    await send({"type":"http.response.start", "status":status, "headers":headers})
    await send({"type":"http.response.body", "body":json.dumps(body).encode()})


class BearerAuth:
    """Authenticate before reading a request body or entering the MCP app."""
    def __init__(self, app, token, audit=None):
        self.app, self.audit = app, audit
        self._digest = hashlib.sha256(validate_token(token).encode("ascii")).digest()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        started = time.monotonic()
        headers = [value for name, value in scope.get("headers", []) if name.lower() == b"authorization"]
        authorized = False
        if len(headers) == 1:
            scheme, separator, candidate = headers[0].partition(b" ")
            if scheme.lower() == b"bearer" and separator and len(candidate) == 43:
                authorized = secrets.compare_digest(hashlib.sha256(candidate).digest(), self._digest)
        if not authorized:
            code = "auth_required" if not headers else "invalid_token"
            if self.audit:
                try:
                    self.audit.write(authentication="failed", code=code, latency_ms=(time.monotonic()-started)*1000)
                except Exception:
                    pass  # Still deny access; never include logging errors or headers.
            await http_error(send, code, 401)
            return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("init", "check", "rotate"))
    parser.add_argument("--credential-file", type=Path, default=DEFAULT_CREDENTIAL)
    args = parser.parse_args()
    try:
        if args.operation == "init":
            provision_credential(args.credential_file)
        elif args.operation == "rotate":
            rotate_credential(args.credential_file)
        else:
            load_credential(args.credential_file)
    except Exception:
        print("MCP credential setup/check failed; service remains closed.", file=sys.stderr)
        return 1
    print("MCP credential ready for the current Windows user. Value is not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
