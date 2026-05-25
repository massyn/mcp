"""Minimal OAuth 2.1 authorisation server for relay (single-user, static client)."""

import base64
import hashlib
import html
import json
import logging
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_log = logging.getLogger("relay.oauth")

_pending: dict[str, dict] = {}  # request_token -> pending authorisation params
_codes: dict[str, dict] = {}    # code -> redeemable params

_PENDING_TTL = 600   # seconds — time to complete the browser approval step
_CODE_TTL = 300      # seconds — time to exchange the code for a token


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def is_oauth_path(path: str) -> bool:
    """Return True for paths that must bypass bearer-token authentication."""
    return path.startswith("/.well-known/") or path in (
        "/mcp/authorize",
        "/mcp/token",
    )


async def dispatch(
    scope, receive, send,
    *,
    base_url: str,
    relay_token: str,
    client_id: str,
    client_secret: str,
) -> bool:
    """Handle an OAuth request. Returns True if handled, False otherwise."""
    if scope["type"] != "http":
        return False

    path = scope["path"]
    method = scope.get("method", "GET").upper()

    if path == "/.well-known/oauth-authorization-server" or path.startswith(
        "/.well-known/oauth-authorization-server/"
    ):
        await _json(send, _server_metadata(base_url))

    elif path.startswith("/.well-known/oauth-protected-resource"):
        await _json(send, _resource_metadata(base_url))

    elif path == "/mcp/authorize" and method == "GET":
        await _authorize_get(scope, send, client_id)

    elif path == "/mcp/authorize" and method == "POST":
        await _authorize_post(receive, send)

    elif path == "/mcp/token" and method == "POST":
        await _token(scope, receive, send, relay_token, client_id, client_secret)

    else:
        return False

    return True


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _resource_metadata(base_url: str) -> dict:
    return {
        "resource": base_url,
        "authorization_servers": [base_url],
    }


def _server_metadata(base_url: str) -> dict:
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _authorize_get(scope, send, expected_client_id: str) -> None:
    params = _qs(scope.get("query_string", b"").decode())

    if params.get("client_id") != expected_client_id:
        await _oauth_error(send, "unauthorized_client", "Unknown client_id")
        return

    challenge = params.get("code_challenge", "")
    if not challenge:
        await _oauth_error(send, "invalid_request", "code_challenge is required")
        return

    req_token = secrets.token_urlsafe(16)
    _pending[req_token] = {
        "client_id": params.get("client_id", ""),
        "redirect_uri": params.get("redirect_uri", ""),
        "state": params.get("state", ""),
        "code_challenge": challenge,
        "code_challenge_method": params.get("code_challenge_method", "S256"),
        "expires": time.time() + _PENDING_TTL,
    }
    await _html(send, _approval_page(req_token, params.get("client_id", "")).encode())


async def _authorize_post(receive, send) -> None:
    params = _qs((await _body(receive)).decode())
    req_token = params.get("request_token", "")
    approved = params.get("approved") == "yes"

    entry = _pending.pop(req_token, None)
    if not entry or time.time() > entry["expires"]:
        await _oauth_error(send, "invalid_request", "Session expired — please try again")
        return

    redirect_uri = entry["redirect_uri"]
    state = entry["state"]

    if not approved:
        await _redirect(send, redirect_uri, {"error": "access_denied", "state": state})
        return

    code = secrets.token_urlsafe(32)
    _codes[code] = {**entry, "expires": time.time() + _CODE_TTL}
    _log.info("Authorisation code issued for client: %s", entry["client_id"])
    await _redirect(send, redirect_uri, {"code": code, "state": state})


async def _token(scope, receive, send, relay_token: str, expected_client_id: str, expected_secret: str) -> None:
    raw_body = await _body(receive)
    params = _qs(raw_body.decode())

    # Accept client credentials from POST body or HTTP Basic auth header.
    client_id, client_secret = _extract_client_credentials(scope, params)

    if not secrets.compare_digest(client_id, expected_client_id) or \
       not secrets.compare_digest(client_secret, expected_secret):
        await _oauth_error(send, "invalid_client", "Invalid client credentials", status=401)
        return

    if params.get("grant_type") != "authorization_code":
        await _oauth_error(send, "unsupported_grant_type")
        return

    code = params.get("code", "")
    entry = _codes.pop(code, None)
    if not entry or time.time() > entry["expires"]:
        await _oauth_error(send, "invalid_grant", "Code expired or invalid")
        return

    # Verify PKCE (S256 only).
    verifier = params.get("code_verifier", "")
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    if not secrets.compare_digest(expected_challenge, entry["code_challenge"]):
        await _oauth_error(send, "invalid_grant", "PKCE verification failed")
        return

    _log.info("Token issued for client: %s", entry["client_id"])
    await _json(send, {
        "access_token": relay_token,
        "token_type": "bearer",
        "expires_in": 3153600000,  # static token; large value satisfies the spec
    })


def _extract_client_credentials(scope, params: dict) -> tuple[str, str]:
    """Return (client_id, client_secret) from POST body or Basic auth header."""
    # Prefer POST body values if present.
    if params.get("client_id"):
        return params.get("client_id", ""), params.get("client_secret", "")

    # Fall back to Authorization: Basic <base64(id:secret)>
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    auth = headers.get(b"authorization", b"").decode()
    if auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode()
            cid, _, csecret = decoded.partition(":")
            return cid, csecret
        except Exception:
            pass

    return "", ""


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _approval_page(request_token: str, client_id: str) -> str:
    safe_client = html.escape(client_id)
    safe_token = html.escape(request_token)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Authorise Access</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #f5f5f5;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
    }}
    .card {{
      background: #fff;
      border-radius: 10px;
      box-shadow: 0 2px 12px rgba(0,0,0,.1);
      padding: 2rem;
      max-width: 400px;
      width: 100%;
    }}
    h2 {{ margin: 0 0 .5rem; font-size: 1.3rem; }}
    p  {{ color: #555; margin: 0 0 1.75rem; line-height: 1.5; }}
    .actions {{ display: flex; gap: .75rem; }}
    .btn {{
      flex: 1;
      padding: .65rem 1rem;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 1rem;
      font-weight: 500;
    }}
    .allow {{ background: #2563eb; color: #fff; }}
    .allow:hover {{ background: #1d4ed8; }}
    .deny  {{ background: #e5e7eb; color: #111; }}
    .deny:hover  {{ background: #d1d5db; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>Authorise Access</h2>
    <p>
      The client <strong>{safe_client}</strong> is requesting access
      to this relay server. Only allow if you initiated this connection.
    </p>
    <form method="post" class="actions">
      <input type="hidden" name="request_token" value="{safe_token}">
      <button class="btn allow" name="approved" value="yes">Allow</button>
      <button class="btn deny"  name="approved" value="no">Deny</button>
    </form>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# ASGI helpers
# ---------------------------------------------------------------------------

async def _json(send, data: dict, status: int = 200) -> None:
    body = json.dumps(data).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
            [b"cache-control", b"no-store"],
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def _html(send, body: bytes) -> None:
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"text/html; charset=utf-8"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def _redirect(send, redirect_uri: str, params: dict) -> None:
    qs = urlencode({k: v for k, v in params.items() if v})
    parsed = urlparse(redirect_uri)
    location = urlunparse(parsed._replace(query=qs))
    await send({
        "type": "http.response.start",
        "status": 302,
        "headers": [[b"location", location.encode()]],
    })
    await send({"type": "http.response.body", "body": b""})


async def _oauth_error(send, error: str, description: str = "", status: int = 400) -> None:
    await _json(send, {"error": error, "error_description": description}, status=status)


async def _body(receive) -> bytes:
    chunks = []
    while True:
        msg = await receive()
        chunks.append(msg.get("body", b""))
        if not msg.get("more_body"):
            break
    return b"".join(chunks)


def _qs(raw: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
