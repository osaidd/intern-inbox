"""Microsoft device-code OAuth for Outlook IMAP — stdlib only, no MSAL.

Microsoft retired password/app-password IMAP in 2024, so Outlook (personal or
school M365) authenticates with a short device-code sign-in instead: the app
shows a code, you enter it at microsoft.com/devicelogin, and the ONLY scope
requested is IMAP mailbox access (IMAP.AccessAsUser.All) + offline_access for
the refresh token. Tokens live in the gitignored data/outlook_token.json and
are revocable any time at account.microsoft.com (Security → app access).

Requires a (free, one-time) Azure public-client app registration; its client id
is NOT a secret — set it in config [mail].outlook_client_id or OUTLOOK_CLIENT_ID.
School tenants sometimes require admin consent for third-party apps; the sign-in
page says so explicitly if yours does.

CLI connect:  uv run python -m feeds.outlook_auth
Writes: data/outlook_token.json only."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = ROOT / "data" / "outlook_token.json"
AUTH_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0"
SCOPE = "https://outlook.office365.com/IMAP.AccessAsUser.All offline_access"
IMAP_HOST = "outlook.office365.com"


def client_id(cfg=None) -> str:
    env = os.environ.get("OUTLOOK_CLIENT_ID", "").strip()
    if env:
        return env
    return (getattr(cfg, "outlook_client_id", "") or "").strip()


def _post(url: str, data: dict) -> dict:
    """POST form-encoded, JSON back. Microsoft answers pending polls with HTTP
    400 + an `error` field, so HTTPError bodies are parsed, never raised away."""
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except ValueError:
            return {"error": f"http_{e.code}"}


def start_device_flow(cid: str, _post=_post) -> dict:
    """-> {device_code, user_code, verification_uri, interval, expires_in}"""
    out = _post(f"{AUTH_BASE}/devicecode", {"client_id": cid, "scope": SCOPE})
    if "device_code" not in out:
        raise RuntimeError(out.get("error_description") or out.get("error")
                           or "device-code request failed")
    return out


def _save(tokens: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": time.time() + int(tokens.get("expires_in", 3600)) - 60,
    }
    TOKEN_PATH.write_text(json.dumps(cache))
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass


def _load() -> dict | None:
    try:
        return json.loads(TOKEN_PATH.read_text())
    except (OSError, ValueError):
        return None


def poll_once(cid: str, device_code: str, _post=_post) -> dict:
    """One token poll: {'status': 'pending'|'connected'|'error', ...}."""
    out = _post(f"{AUTH_BASE}/token", {
        "client_id": cid, "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    if "access_token" in out:
        _save(out)
        return {"status": "connected"}
    err = out.get("error", "")
    if err in ("authorization_pending", "slow_down"):
        return {"status": "pending"}
    return {"status": "error",
            "message": out.get("error_description", err)[:200] or "sign-in failed"}


def get_access_token(cid: str, _post=_post) -> str | None:
    """Cached token, refreshed when stale. None = not connected (or revoked)."""
    cache = _load()
    if not cache:
        return None
    if cache.get("expires_at", 0) > time.time() and cache.get("access_token"):
        return cache["access_token"]
    if not cache.get("refresh_token"):
        return None
    out = _post(f"{AUTH_BASE}/token", {
        "client_id": cid, "grant_type": "refresh_token",
        "refresh_token": cache["refresh_token"], "scope": SCOPE})
    if "access_token" not in out:
        return None            # revoked/expired — reconnect in the app
    out.setdefault("refresh_token", cache["refresh_token"])  # MS may not rotate
    _save(out)
    return out["access_token"]


def connected() -> bool:
    cache = _load()
    return bool(cache and cache.get("refresh_token"))


def disconnect() -> None:
    TOKEN_PATH.unlink(missing_ok=True)


def xoauth2(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def main() -> None:
    from career_hunt import config as ch_config
    cid = client_id(ch_config.load())
    if not cid:
        sys.exit("no client id — set [mail].outlook_client_id in config/career.toml "
                 "or OUTLOOK_CLIENT_ID in config/.env (see SETUP.md)")
    flow = start_device_flow(cid)
    print(f"\nGo to {flow['verification_uri']} and enter code: {flow['user_code']}\n")
    deadline = time.time() + int(flow.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(int(flow.get("interval", 5)))
        out = poll_once(cid, flow["device_code"])
        if out["status"] == "connected":
            print("Connected — Outlook IMAP is ready.")
            return
        if out["status"] == "error":
            sys.exit(f"sign-in failed: {out.get('message')}")
    sys.exit("code expired — run this again")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
