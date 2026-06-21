"""Primitive cookie auth powered by TOML credentials."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import secrets
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTH_FILE = PROJECT_ROOT / "auth.toml"
DEFAULT_AUTH_REVOCATIONS_FILE = PROJECT_ROOT / "data" / "auth-session-revocations.json"
SESSION_COOKIE_NAME = "contadores_session"
CSRF_COOKIE_NAME = "contadores_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
INTERNAL_API_TOKEN_HEADER = "X-Internal-Token"
PRODUCTION_APP_ENVS = {"prod", "production"}
AUTH_CAPABILITIES = frozenset(
    {
        "campaigns:write",
        "config:write",
        "delivery:write",
        "leads:write",
        "meta:publish",
        "workstation:write",
    }
)
ROLE_CAPABILITIES = {
    "admin": AUTH_CAPABILITIES,
    "operator": AUTH_CAPABILITIES,
    "viewer": frozenset(),
}

LOGIN_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Contadores Login</title>
  <style>
    :root {
      color-scheme: light;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Space Grotesk", "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(120% 100% at 100% -20%, rgba(15, 143, 122, 0.2) 0%, transparent 56%),
        linear-gradient(165deg, #edf6ef 0%, #d4e7d8 100%);
      color: #12302b;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .login-card {
      width: min(440px, 100%);
      border: 1px solid rgba(21, 95, 77, 0.22);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.86);
      box-shadow: 0 18px 42px rgba(18, 48, 43, 0.16);
      backdrop-filter: blur(8px);
      padding: 28px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 1.5rem;
      line-height: 1.2;
    }
    p {
      margin: 0;
      color: #33584f;
    }
    form {
      margin-top: 18px;
      display: grid;
      gap: 12px;
    }
    label {
      font-size: 0.86rem;
      color: #2e4d45;
      display: grid;
      gap: 6px;
    }
    input {
      width: 100%;
      border: 1px solid #aac4b6;
      border-radius: 10px;
      padding: 10px 12px;
      font: inherit;
      background: #f7fcf8;
      color: #143730;
    }
    button {
      margin-top: 2px;
      border: none;
      border-radius: 10px;
      padding: 11px 14px;
      font: 600 0.94rem "Space Grotesk", "Avenir Next", "Segoe UI", sans-serif;
      background: #0e8f78;
      color: #fff;
      cursor: pointer;
    }
    button:disabled {
      opacity: 0.62;
      cursor: wait;
    }
    .error {
      margin-top: 10px;
      min-height: 20px;
      font-size: 0.84rem;
      color: #9e2f2f;
    }
  </style>
</head>
<body>
  <main class="login-card">
    <h1>Contadores</h1>
    <p>Sign in to access the backoffice.</p>
    <form id="loginForm" novalidate>
      <label>
        User
        <input id="userInput" name="user" type="text" autocomplete="username" required>
      </label>
      <label>
        Password
        <input id="passwordInput" name="password" type="password" autocomplete="current-password" required>
      </label>
      <button id="submitBtn" type="submit">Login</button>
      <p id="errorText" class="error" role="status" aria-live="polite"></p>
    </form>
  </main>
  <script>
    const form = document.getElementById("loginForm");
    const submitBtn = document.getElementById("submitBtn");
    const errorText = document.getElementById("errorText");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorText.textContent = "";
      submitBtn.disabled = true;
      submitBtn.textContent = "Logging in...";

      const payload = {
        user: String(document.getElementById("userInput").value || "").trim(),
        password: String(document.getElementById("passwordInput").value || ""),
      };

      try {
        const response = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          credentials: "same-origin",
        });

        if (!response.ok) {
          let detail = "Invalid credentials";
          try {
            const parsed = await response.json();
            if (parsed && parsed.detail) {
              detail = String(parsed.detail);
            }
          } catch {}
          throw new Error(detail);
        }
        const next = new URLSearchParams(window.location.search).get("next") || "/";
        const redirectPath = next.startsWith("/") && !next.startsWith("//") ? next : "/";
        window.location.replace(redirectPath);
      } catch (error) {
        errorText.textContent = error && error.message ? error.message : "Login failed";
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Login";
      }
    });
  </script>
</body>
</html>
"""


def _normalize_user(value: str) -> str:
    """Normalize account user for lookup keys."""
    return value.strip().lower()


def _parse_bool_env(name: str, *, default: bool) -> bool:
    """Read bool-like environment flags with sane defaults."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_session_hours(value: str) -> int:
    """Parse session duration from env and clamp to minimum 1 hour."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError("AUTH_SESSION_HOURS must be an integer >= 1.") from exc
    if parsed < 1:
        raise RuntimeError("AUTH_SESSION_HOURS must be >= 1.")
    return parsed


@dataclass(frozen=True)
class AuthAccount:
    """One configured auth account with server-owned capabilities."""

    user: str
    password: str
    capabilities: frozenset[str]


def _is_production_env() -> bool:
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower() in PRODUCTION_APP_ENVS


def get_internal_api_token() -> str:
    """Return shared internal token used by bot/backend machine clients."""
    return (os.getenv("INTERNAL_API_TOKEN") or "").strip()


def has_valid_internal_api_token(value: str | None) -> bool:
    """Return True when provided token matches configured internal token."""
    expected = get_internal_api_token()
    provided = (value or "").strip()
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)


def _string_list(value: object, *, field: str, user: str) -> list[str]:
    """Read a TOML string-or-list field."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
        if all(items):
            return items
    raise RuntimeError(f"`{field}` for auth user `{user}` must be a string or list of strings.")


def _account_capabilities(user: str, item: dict[str, Any]) -> frozenset[str]:
    """Resolve roles/capabilities from one TOML account item."""
    roles = _string_list(item.get("roles", item.get("role")), field="role", user=user)
    requested = _string_list(
        item.get("capabilities", item.get("capability")),
        field="capabilities",
        user=user,
    )
    if not roles and not requested:
        roles = ["admin"]

    capabilities: set[str] = set()
    for role in roles:
        clean_role = role.strip().lower()
        if clean_role not in ROLE_CAPABILITIES:
            raise RuntimeError(f"Unknown auth role `{clean_role}` for user `{user}`.")
        capabilities.update(ROLE_CAPABILITIES[clean_role])

    for capability in requested:
        clean_capability = capability.strip().lower()
        if clean_capability == "*":
            capabilities.update(AUTH_CAPABILITIES)
            continue
        if clean_capability not in AUTH_CAPABILITIES:
            raise RuntimeError(f"Unknown auth capability `{clean_capability}` for user `{user}`.")
        capabilities.add(clean_capability)
    return frozenset(capabilities)


def _build_auth_account(user: str, password: str, item: dict[str, Any] | None = None) -> AuthAccount:
    """Build one normalized account entry."""
    return AuthAccount(
        user=user,
        password=password,
        capabilities=_account_capabilities(user, item or {}),
    )


def _extract_toml_users(raw: dict[str, Any]) -> list[AuthAccount]:
    """Read account entries from `[users]` or `[[users]]` sections."""
    entries: list[AuthAccount] = []
    for section_name in ("users", "accounts"):
        section = raw.get(section_name)
        if isinstance(section, dict):
            for user, value in section.items():
                if isinstance(value, dict):
                    account_user = str(value.get("user", value.get("username", user))).strip()
                    password = str(value.get("password", ""))
                    entries.append(_build_auth_account(account_user, password, value))
                    continue
                entries.append(_build_auth_account(str(user), str(value)))
            continue
        if isinstance(section, list):
            for index, item in enumerate(section):
                if not isinstance(item, dict):
                    raise RuntimeError(
                        f"{section_name}[{index}] must be a table with `user` and `password`."
                    )
                user = str(item.get("user", "") or item.get("username", "")).strip()
                password = str(item.get("password", ""))
                entries.append(_build_auth_account(user, password, item))
    return entries


class PrimitiveAuthManager:
    """Simple in-memory auth/session manager."""

    def __init__(self) -> None:
        self._enabled = False
        self._accounts: dict[str, str] = {}
        self._account_capabilities: dict[str, frozenset[str]] = {}
        self._signing_key = b""
        self._session_duration = timedelta(hours=24)
        self._cookie_secure = False
        self._revoked_sessions: dict[str, datetime] = {}
        self._revocations_path = DEFAULT_AUTH_REVOCATIONS_FILE
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        """Return True when auth middleware should enforce sessions."""
        return self._enabled

    @property
    def cookie_secure(self) -> bool:
        """Expose secure-cookie flag for endpoint cookie writes."""
        return self._cookie_secure

    @property
    def session_max_age_seconds(self) -> int:
        """Expose cookie/session duration in seconds."""
        return max(60, int(self._session_duration.total_seconds()))

    def reload_from_env(self) -> None:
        """Load accounts/config from env + TOML."""
        if _parse_bool_env("AUTH_DISABLE", default=False):
            if _is_production_env() and not _parse_bool_env("AUTH_DISABLE_LOCAL_ONLY", default=False):
                raise RuntimeError(
                    "AUTH_DISABLE=true is not allowed when APP_ENV/ENVIRONMENT is production. "
                    "Set AUTH_DISABLE_LOCAL_ONLY=true only for local tests or isolated development."
                )
            with self._lock:
                self._enabled = False
                self._accounts = {}
                self._account_capabilities = {}
                self._signing_key = b""
                self._cookie_secure = False
                self._session_duration = timedelta(hours=24)
                self._revoked_sessions = {}
                self._revocations_path = self._resolve_revocations_path()
            return

        auth_path = Path(
            os.getenv("AUTH_TOML", os.getenv("AUTH_USERS_TOML", str(DEFAULT_AUTH_FILE)))
        ).expanduser()
        accounts, account_capabilities = self._load_accounts(auth_path)
        signing_key = self._load_signing_key(auth_path)
        session_hours = _parse_session_hours(os.getenv("AUTH_SESSION_HOURS", "24"))
        cookie_secure = _parse_bool_env("AUTH_COOKIE_SECURE", default=True)
        revocations_path = self._resolve_revocations_path()
        revoked_sessions = self._load_revoked_sessions(revocations_path, self._utc_now())

        with self._lock:
            self._enabled = True
            self._accounts = accounts
            self._account_capabilities = account_capabilities
            self._signing_key = signing_key
            self._session_duration = timedelta(hours=session_hours)
            self._cookie_secure = cookie_secure
            self._revoked_sessions = revoked_sessions
            self._revocations_path = revocations_path

    def authenticate(self, user: str, password: str) -> str | None:
        """Validate credentials and return normalized user on success."""
        normalized_user = _normalize_user(user)
        with self._lock:
            expected_password = self._accounts.get(normalized_user)
        if expected_password is None:
            return None
        if not secrets.compare_digest(expected_password, password):
            return None
        return normalized_user

    def capabilities_for_user(self, user: str) -> frozenset[str]:
        """Return server-resolved capabilities for a configured user."""
        normalized_user = _normalize_user(user)
        with self._lock:
            return self._account_capabilities.get(normalized_user, frozenset())

    def user_has_capability(self, user: str, capability: str) -> bool:
        """Return True when the user has one server-owned capability."""
        return capability in self.capabilities_for_user(user)

    def create_session(self, user: str) -> str:
        """Create a signed session token for the authenticated user."""
        normalized_user = _normalize_user(user)
        with self._lock:
            signing_key = self._signing_key
            expires_at = self._utc_now() + self._session_duration
        payload = {
            "u": normalized_user,
            "e": int(expires_at.timestamp()),
            "sid": secrets.token_urlsafe(16),
        }
        return self._encode_signed_token(payload, signing_key)

    def create_csrf_token(self, session_token: str | None) -> str | None:
        """Create a non-secret token bound to one valid session cookie."""
        if not session_token or not self.resolve_session(session_token):
            return None
        with self._lock:
            signing_key = self._signing_key
        payload = {
            "p": "csrf",
            "s": self._csrf_session_digest(session_token, signing_key),
        }
        return self._encode_signed_token(payload, signing_key)

    def validate_csrf_token(self, session_token: str | None, csrf_token: str | None) -> bool:
        """Validate a CSRF token against the current session cookie."""
        if not session_token or not csrf_token or not self.resolve_session(session_token):
            return False
        with self._lock:
            signing_key = self._signing_key
        payload = self._decode_signed_token(csrf_token.strip(), signing_key)
        if not payload or payload.get("p") != "csrf":
            return False
        expected = self._csrf_session_digest(session_token, signing_key)
        provided = str(payload.get("s", ""))
        return bool(provided) and secrets.compare_digest(expected, provided)

    def resolve_session(self, session_token: str | None) -> str | None:
        """Resolve signed session token to user, returning None for invalid/expired sessions."""
        if not session_token:
            return None
        now = self._utc_now()
        with self._lock:
            accounts = dict(self._accounts)
            signing_key = self._signing_key
        if self._is_session_revoked(session_token, signing_key, now):
            return None
        payload = self._decode_signed_token(session_token, signing_key)
        if not payload:
            return None
        user = _normalize_user(str(payload.get("u", "")))
        expires_at = self._coerce_expiry(payload.get("e"))
        if not user or not expires_at:
            return None
        if expires_at <= now:
            return None
        if user not in accounts:
            return None
        return user

    def revoke_session(self, session_token: str | None) -> None:
        """Reject one valid session token for the rest of its lifetime."""
        if not session_token:
            return
        now = self._utc_now()
        with self._lock:
            signing_key = self._signing_key

        payload = self._decode_signed_token(session_token, signing_key)
        if not payload:
            return

        expires_at = self._coerce_expiry(payload.get("e"))
        if not expires_at or expires_at <= now:
            return

        with self._lock:
            self._prune_revoked_sessions(now)
            self._revoked_sessions[self._revocation_key(session_token, signing_key)] = expires_at
            self._write_revoked_sessions()

    def session_expires_at(self, session_token: str | None) -> datetime | None:
        """Return a valid session token expiry without extending it."""
        if not session_token:
            return None
        with self._lock:
            signing_key = self._signing_key
        payload = self._decode_signed_token(session_token, signing_key)
        if not payload:
            return None
        return self._coerce_expiry(payload.get("e"))

    def _is_session_revoked(self, session_token: str, signing_key: bytes, now: datetime) -> bool:
        """Return True when logout already revoked this exact token."""
        revocation_key = self._revocation_key(session_token, signing_key)
        with self._lock:
            changed = self._prune_revoked_sessions(now)
            if changed:
                self._write_revoked_sessions()
            return revocation_key in self._revoked_sessions

    def _prune_revoked_sessions(self, now: datetime) -> bool:
        """Drop expired revocation entries. Caller must hold the lock."""
        expired_tokens = [
            token
            for token, expires_at in self._revoked_sessions.items()
            if expires_at <= now
        ]
        for token in expired_tokens:
            self._revoked_sessions.pop(token, None)
        return bool(expired_tokens)

    def _write_revoked_sessions(self) -> None:
        """Persist hashed session revocations. Caller must hold the lock."""
        payload = {
            token_hash: int(expires_at.timestamp())
            for token_hash, expires_at in self._revoked_sessions.items()
        }
        self._revocations_path.parent.mkdir(parents=True, exist_ok=True)
        self._revocations_path.write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def _load_revoked_sessions(cls, path: Path, now: datetime) -> dict[str, datetime]:
        """Load persisted hashed session revocations."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        revoked_sessions: dict[str, datetime] = {}
        for token_hash, expires_value in raw.items():
            if not isinstance(token_hash, str) or not token_hash:
                continue
            expires_at = cls._coerce_expiry(expires_value)
            if expires_at and expires_at > now:
                revoked_sessions[token_hash] = expires_at
        return revoked_sessions

    @staticmethod
    def _resolve_revocations_path() -> Path:
        raw = os.getenv("AUTH_REVOCATIONS_PATH", "").strip()
        return Path(raw).expanduser() if raw else DEFAULT_AUTH_REVOCATIONS_FILE

    @staticmethod
    def _revocation_key(session_token: str, signing_key: bytes) -> str:
        return hmac.new(
            signing_key,
            f"revoked:{session_token}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _coerce_expiry(value: object) -> datetime | None:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        try:
            return datetime.fromtimestamp(timestamp, UTC)
        except (OverflowError, OSError, ValueError):
            return None

    @staticmethod
    def _csrf_session_digest(session_token: str, signing_key: bytes) -> str:
        return hmac.new(
            signing_key,
            f"csrf:{session_token}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _urlsafe_b64encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    @staticmethod
    def _urlsafe_b64decode(raw: str) -> bytes | None:
        try:
            padded = raw + ("=" * (-len(raw) % 4))
            return base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            return None

    @classmethod
    def _encode_signed_token(cls, payload: dict[str, object], signing_key: bytes) -> str:
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encoded_payload = cls._urlsafe_b64encode(payload_bytes)
        signature = hmac.new(signing_key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        encoded_signature = cls._urlsafe_b64encode(signature)
        return f"{encoded_payload}.{encoded_signature}"

    @classmethod
    def _decode_signed_token(
        cls,
        token: str,
        signing_key: bytes,
    ) -> dict[str, object] | None:
        encoded_payload, separator, encoded_signature = token.partition(".")
        if not separator or not encoded_payload or not encoded_signature:
            return None
        expected_signature = hmac.new(
            signing_key,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        provided_signature = cls._urlsafe_b64decode(encoded_signature)
        if not provided_signature:
            return None
        if not secrets.compare_digest(expected_signature, provided_signature):
            return None
        payload_bytes = cls._urlsafe_b64decode(encoded_payload)
        if not payload_bytes:
            return None
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    @staticmethod
    def _load_signing_key(auth_path: Path) -> bytes:
        secret = os.getenv("AUTH_SECRET_KEY", "").strip()
        if secret:
            return hashlib.sha256(secret.encode("utf-8")).digest()
        resolved_path = auth_path.resolve()
        try:
            raw_bytes = resolved_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Unable to read auth file for signing at `{resolved_path}`.") from exc
        return hashlib.sha256(
            b"contadores-auth-cookie\n" + resolved_path.as_posix().encode("utf-8") + b"\n" + raw_bytes
        ).digest()

    @staticmethod
    def _load_accounts(users_path: Path) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
        resolved_path = users_path.resolve()
        if not resolved_path.exists():
            raise RuntimeError(
                f"Auth file not found at `{resolved_path}`. "
                "Create `auth.toml` or set AUTH_DISABLE=true."
            )
        if not resolved_path.is_file():
            raise RuntimeError(f"Auth path must be a file: `{resolved_path}`.")

        try:
            raw = tomllib.loads(resolved_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - parser errors are env/data specific.
            raise RuntimeError(f"Invalid auth TOML at `{resolved_path}`.") from exc

        account_pairs = _extract_toml_users(raw)
        normalized_accounts: dict[str, str] = {}
        account_capabilities: dict[str, frozenset[str]] = {}
        for account in account_pairs:
            normalized_user = _normalize_user(account.user)
            if not normalized_user:
                raise RuntimeError(f"Invalid auth user entry: `{account.user}`.")
            if any(char.isspace() for char in normalized_user):
                raise RuntimeError(f"Auth user cannot contain spaces: `{normalized_user}`.")
            if not account.password:
                raise RuntimeError(f"Password cannot be empty for `{normalized_user}`.")
            normalized_accounts[normalized_user] = account.password
            account_capabilities[normalized_user] = account.capabilities

        if not normalized_accounts:
            raise RuntimeError(
                f"No users found in `{resolved_path}`. Use `[users]` or `[[users]]` entries."
            )
        return normalized_accounts, account_capabilities


auth_manager = PrimitiveAuthManager()


class CliLoginTicketManager:
    """Short-lived one-time browser-login codes for CLI sessions."""

    def __init__(
        self,
        session_manager: PrimitiveAuthManager,
        *,
        code_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        self._session_manager = session_manager
        self._code_duration = code_duration
        self._codes: dict[str, dict[str, object]] = {}
        self._lock = Lock()

    def create_code(self, user: str) -> dict[str, object]:
        """Create one exchange code bound to a signed CLI session token."""
        clean_user = _normalize_user(user)
        session_token = self._session_manager.create_session(clean_user)
        now = datetime.now(UTC)
        code = secrets.token_urlsafe(32)
        session_expires_at = self._session_manager.session_expires_at(session_token)
        entry = {
            "code": code,
            "user": clean_user,
            "session_token": session_token,
            "expires_at": now + self._code_duration,
            "session_expires_at": session_expires_at,
        }
        with self._lock:
            self._prune(now)
            self._codes[code] = entry
        return entry

    def exchange_code(self, code: str) -> dict[str, object] | None:
        """Consume a one-time login code and return its session payload."""
        clean_code = (code or "").strip()
        if not clean_code:
            return None
        now = datetime.now(UTC)
        with self._lock:
            self._prune(now)
            entry = self._codes.pop(clean_code, None)
        if entry is None:
            return None
        expires_at = entry.get("expires_at")
        if not isinstance(expires_at, datetime) or expires_at <= now:
            self._session_manager.revoke_session(str(entry.get("session_token") or ""))
            return None
        session_token = str(entry.get("session_token") or "")
        user = self._session_manager.resolve_session(session_token)
        if not user:
            return None
        return {
            "authenticated": True,
            "user": user,
            "session_token": session_token,
            "expires_at": _iso_datetime(entry.get("session_expires_at")),
        }

    def _prune(self, now: datetime) -> None:
        expired_codes = [
            code
            for code, entry in self._codes.items()
            if not isinstance(entry.get("expires_at"), datetime) or entry["expires_at"] <= now
        ]
        for code in expired_codes:
            self._codes.pop(code, None)


def _iso_datetime(value: object) -> str | None:
    """Serialize aware datetimes for API responses."""
    if isinstance(value, datetime):
        return value.isoformat()
    return None


cli_login_manager = CliLoginTicketManager(auth_manager)
