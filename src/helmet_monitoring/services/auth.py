from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from helmet_monitoring.core.config import REPO_ROOT


UTC = timezone.utc
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
DEFAULT_HASH_ITERATIONS = 390_000
DEFAULT_AUTH_USERS_FILE = "artifacts/runtime/ops/auth_users.json"
DEFAULT_AUTH_ATTEMPTS_FILE = "artifacts/runtime/ops/auth_attempts.json"
DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 15 * 60
DEFAULT_SESSION_TIMEOUT_SECONDS = 30 * 60

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"review.assign", "review.update", "camera.edit", "account.manage"}),
    "safety_manager": frozenset({"review.assign", "review.update"}),
    "team_lead": frozenset({"review.assign", "review.update"}),
    "viewer": frozenset(),
}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _normalize_username(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_role(value: str | None, *, default: str = "viewer") -> str:
    role = str(value or "").strip().lower()
    return role if role in ROLE_PERMISSIONS else default


def _display_name_from_username(username: str) -> str:
    return username or "operator"


def _encode_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_b64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(rendered)

    last_error: OSError | None = None
    for _ in range(8):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)

    for _ in range(8):
        try:
            with path.open("w", encoding="utf-8") as handle:
                handle.write(rendered)
            temp_path.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)

    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass
    if last_error is not None:
        raise last_error


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_password_hash(password_hash: str) -> tuple[int, bytes, bytes] | None:
    try:
        scheme, raw_iterations, raw_salt, raw_digest = str(password_hash).split("$", 3)
        if scheme != PASSWORD_HASH_SCHEME:
            return None
        iterations = int(raw_iterations)
        if iterations < 100_000:
            return None
        salt = _decode_b64(raw_salt)
        digest = _decode_b64(raw_digest)
    except (TypeError, ValueError):
        return None
    if len(salt) < 8 or not digest:
        return None
    return iterations, salt, digest


def _normalize_password_hash_text(value: str | None) -> str:
    # Docker Compose users often escape "$" as "$$" inside .env files.
    return str(value or "").strip().replace("$$", "$")


def _parse_env_int(env: Mapping[str, str], key: str, default: int, minimum: int) -> int:
    raw_value = str(env.get(key, "")).strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return max(minimum, parsed)


def _resolve_repo_path(path_value: str | Path, *, repo_root: Path | None = None) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    return ((repo_root or REPO_ROOT) / candidate).resolve()


@dataclass(slots=True, frozen=True)
class AuthPolicy:
    max_failed_attempts: int = DEFAULT_MAX_FAILED_ATTEMPTS
    lockout_seconds: int = DEFAULT_LOCKOUT_SECONDS
    session_timeout_seconds: int = DEFAULT_SESSION_TIMEOUT_SECONDS


@dataclass(slots=True, frozen=True)
class TrustedIdentity:
    username: str
    role: str
    display_name: str
    email: str = ""

    def to_record(self) -> dict[str, str]:
        return {
            "username": self.username,
            "role": self.role,
            "display_name": self.display_name,
            "email": self.email,
        }

    @classmethod
    def from_record(cls, payload: Mapping[str, object]) -> TrustedIdentity:
        username = _normalize_username(str(payload.get("username", "")))
        if not username:
            raise ValueError("Trusted identity username is required.")
        role = _normalize_role(str(payload.get("role", "")))
        display_name = str(payload.get("display_name") or "").strip() or _display_name_from_username(username)
        email = str(payload.get("email") or "").strip()
        return cls(username=username, role=role, display_name=display_name, email=email)


@dataclass(slots=True, frozen=True)
class AuthAccount:
    username: str
    role: str
    display_name: str
    password_hash: str
    email: str = ""
    source: str = "managed_file"

    def to_identity(self) -> TrustedIdentity:
        return TrustedIdentity(
            username=self.username,
            role=self.role,
            display_name=self.display_name,
            email=self.email,
        )

    def to_record(self) -> dict[str, str]:
        return {
            "username": self.username,
            "role": self.role,
            "display_name": self.display_name,
            "email": self.email,
            "password_hash": self.password_hash,
        }


@dataclass(slots=True, frozen=True)
class LoginLockoutState:
    username: str
    failed_attempts: int = 0
    locked_until: datetime | None = None
    last_failed_at: datetime | None = None

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > utc_now()

    def remaining_seconds(self, *, now: datetime | None = None) -> int:
        if self.locked_until is None:
            return 0
        current = now or utc_now()
        return max(0, int((self.locked_until - current).total_seconds()))

    def to_record(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {"failed_attempts": int(self.failed_attempts)}
        if self.locked_until is not None:
            payload["locked_until"] = self.locked_until.isoformat()
        if self.last_failed_at is not None:
            payload["last_failed_at"] = self.last_failed_at.isoformat()
        return payload


def load_auth_policy(env: Mapping[str, str] | None = None) -> AuthPolicy:
    raw_env = env if env is not None else os.environ
    return AuthPolicy(
        max_failed_attempts=_parse_env_int(raw_env, "HELMET_AUTH_MAX_FAILED_ATTEMPTS", DEFAULT_MAX_FAILED_ATTEMPTS, 3),
        lockout_seconds=_parse_env_int(raw_env, "HELMET_AUTH_LOCKOUT_SECONDS", DEFAULT_LOCKOUT_SECONDS, 60),
        session_timeout_seconds=_parse_env_int(
            raw_env,
            "HELMET_AUTH_SESSION_TIMEOUT_SECONDS",
            DEFAULT_SESSION_TIMEOUT_SECONDS,
            300,
        ),
    )


def resolve_auth_users_path(
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> Path:
    raw_env = env if env is not None else os.environ
    candidate = path_value or raw_env.get("HELMET_AUTH_USERS_FILE", DEFAULT_AUTH_USERS_FILE)
    return _resolve_repo_path(candidate, repo_root=repo_root)


def resolve_auth_attempts_path(
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> Path:
    raw_env = env if env is not None else os.environ
    candidate = path_value or raw_env.get("HELMET_AUTH_ATTEMPTS_FILE", DEFAULT_AUTH_ATTEMPTS_FILE)
    return _resolve_repo_path(candidate, repo_root=repo_root)


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = DEFAULT_HASH_ITERATIONS) -> str:
    secret = str(password)
    if not secret:
        raise ValueError("Password cannot be empty.")
    if iterations < 100_000:
        raise ValueError("Password hash iterations must be at least 100000.")

    salt_bytes = salt or secrets.token_bytes(16)
    if len(salt_bytes) < 8:
        raise ValueError("Password salt must be at least 8 bytes.")

    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt_bytes, iterations)
    return f"{PASSWORD_HASH_SCHEME}${iterations}${_encode_b64(salt_bytes)}${_encode_b64(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    parsed = _parse_password_hash(password_hash)
    if parsed is None:
        return False
    iterations, salt, expected = parsed
    candidate = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def generate_temporary_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    target_length = max(8, int(length))
    return "".join(secrets.choice(alphabet) for _ in range(target_length))


def role_has_permission(role: str | None, permission: str) -> bool:
    normalized = _normalize_role(role)
    return permission in ROLE_PERMISSIONS.get(normalized, frozenset())


def require_permission(role: str | None, permission: str) -> None:
    if not role_has_permission(role, permission):
        raise PermissionError(f"Role '{_normalize_role(role)}' is not allowed to perform '{permission}'.")


def _account_from_payload(payload: Mapping[str, object], *, source: str) -> AuthAccount | None:
    username = _normalize_username(str(payload.get("username", "")))
    password_hash = _normalize_password_hash_text(payload.get("password_hash"))
    if not username or not password_hash:
        return None
    if _parse_password_hash(password_hash) is None:
        return None

    role = _normalize_role(str(payload.get("role", "")), default="viewer")
    display_name = str(payload.get("display_name") or "").strip() or _display_name_from_username(username)
    email = str(payload.get("email") or "").strip()
    return AuthAccount(
        username=username,
        role=role,
        display_name=display_name,
        password_hash=password_hash,
        email=email,
        source=source,
    )


def _load_accounts_from_json(raw_value: str, *, source: str) -> list[AuthAccount]:
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        candidates = payload.get("users", [])
    elif isinstance(payload, list):
        candidates = payload
    else:
        return []

    accounts: list[AuthAccount] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        account = _account_from_payload(item, source=source)
        if account is not None:
            accounts.append(account)
    return accounts


def load_managed_auth_accounts(
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> tuple[AuthAccount, ...]:
    target = resolve_auth_users_path(path_value, env=env, repo_root=repo_root)
    payload = _read_json(target, {"users": []})
    if isinstance(payload, dict):
        candidates = payload.get("users", [])
    elif isinstance(payload, list):
        candidates = payload
    else:
        candidates = []

    accounts: list[AuthAccount] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        account = _account_from_payload(item, source="managed_file")
        if account is not None:
            accounts.append(account)
    return tuple(sorted(accounts, key=lambda item: item.username))


def save_managed_auth_accounts(
    accounts: Sequence[AuthAccount],
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> Path:
    target = resolve_auth_users_path(path_value, env=env, repo_root=repo_root)
    payload = {
        "updated_at": utc_now().isoformat(),
        "users": [account.to_record() for account in sorted(accounts, key=lambda item: item.username)],
    }
    _atomic_write_json(target, payload)
    return target


def upsert_managed_auth_account(
    account: AuthAccount,
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> Path:
    existing = {item.username: item for item in load_managed_auth_accounts(path_value, env=env, repo_root=repo_root)}
    existing[account.username] = AuthAccount(
        username=account.username,
        role=account.role,
        display_name=account.display_name,
        password_hash=account.password_hash,
        email=account.email,
        source="managed_file",
    )
    return save_managed_auth_accounts(tuple(existing.values()), path_value, env=env, repo_root=repo_root)


def delete_managed_auth_account(
    username: str,
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> bool:
    normalized = _normalize_username(username)
    existing = {item.username: item for item in load_managed_auth_accounts(path_value, env=env, repo_root=repo_root)}
    removed = existing.pop(normalized, None)
    save_managed_auth_accounts(tuple(existing.values()), path_value, env=env, repo_root=repo_root)
    return removed is not None


def load_bootstrap_admin_account(env: Mapping[str, str] | None = None) -> AuthAccount | None:
    raw_env = env if env is not None else os.environ
    username = _normalize_username(raw_env.get("HELMET_AUTH_ADMIN_USERNAME", ""))
    password_hash = _normalize_password_hash_text(raw_env.get("HELMET_AUTH_ADMIN_PASSWORD_HASH", ""))
    if not username or not password_hash:
        return None
    if _parse_password_hash(password_hash) is None:
        return None
    role = _normalize_role(raw_env.get("HELMET_AUTH_ADMIN_ROLE", "admin"), default="admin")
    display_name = str(raw_env.get("HELMET_AUTH_ADMIN_DISPLAY_NAME", "")).strip() or _display_name_from_username(username)
    email = str(raw_env.get("HELMET_AUTH_ADMIN_EMAIL", "")).strip()
    return AuthAccount(
        username=username,
        role=role,
        display_name=display_name,
        password_hash=password_hash,
        email=email,
        source="bootstrap_admin",
    )


def load_auth_accounts(env: Mapping[str, str] | None = None) -> tuple[AuthAccount, ...]:
    raw_env = env if env is not None else os.environ
    by_username: dict[str, AuthAccount] = {}

    for account in load_managed_auth_accounts(env=raw_env):
        by_username[account.username] = account

    raw_users_json = str(raw_env.get("HELMET_AUTH_USERS_JSON", "")).strip()
    if raw_users_json:
        for account in _load_accounts_from_json(raw_users_json, source="env_json"):
            by_username[account.username] = account

    bootstrap_admin = load_bootstrap_admin_account(raw_env)
    if bootstrap_admin is not None:
        by_username[bootstrap_admin.username] = bootstrap_admin

    return tuple(sorted(by_username.values(), key=lambda item: item.username))


def authenticate_user(username: str, password: str, env: Mapping[str, str] | None = None) -> TrustedIdentity | None:
    normalized_username = _normalize_username(username)
    if not normalized_username or not str(password):
        return None

    for account in load_auth_accounts(env):
        if account.username != normalized_username:
            continue
        if verify_password(password, account.password_hash):
            return account.to_identity()
        return None
    return None


def auth_configuration_summary(env: Mapping[str, str] | None = None) -> dict[str, object]:
    raw_env = env if env is not None else os.environ
    accounts = load_auth_accounts(raw_env)
    managed_accounts = load_managed_auth_accounts(env=raw_env)
    policy = load_auth_policy(raw_env)
    roles = tuple(sorted({account.role for account in accounts}))
    return {
        "configured": bool(accounts),
        "enabled_users": len(accounts),
        "managed_users": len(managed_accounts),
        "roles": roles,
        "has_admin": any(account.role == "admin" for account in accounts),
        "bootstrap_admin_present": load_bootstrap_admin_account(raw_env) is not None,
        "managed_users_path": str(resolve_auth_users_path(env=raw_env)),
        "max_failed_attempts": policy.max_failed_attempts,
        "lockout_seconds": policy.lockout_seconds,
        "session_timeout_seconds": policy.session_timeout_seconds,
    }


def _load_attempt_records(
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    target = resolve_auth_attempts_path(path_value, env=env, repo_root=repo_root)
    payload = _read_json(target, {"users": {}})
    if not isinstance(payload, dict):
        payload = {"users": {}}
    users = payload.get("users")
    if not isinstance(users, dict):
        payload["users"] = {}
    return target, payload


def _build_lockout_state(username: str, record: Mapping[str, object], *, now: datetime | None = None) -> LoginLockoutState:
    current = now or utc_now()
    locked_until = _parse_timestamp(str(record.get("locked_until") or ""))
    if locked_until is not None and locked_until <= current:
        locked_until = None
    last_failed_at = _parse_timestamp(str(record.get("last_failed_at") or ""))
    try:
        failed_attempts = max(0, int(record.get("failed_attempts", 0) or 0))
    except (TypeError, ValueError):
        failed_attempts = 0
    return LoginLockoutState(
        username=_normalize_username(username),
        failed_attempts=failed_attempts,
        locked_until=locked_until,
        last_failed_at=last_failed_at,
    )


def get_login_lockout_state(
    username: str,
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> LoginLockoutState:
    normalized = _normalize_username(username)
    _, payload = _load_attempt_records(path_value, env=env, repo_root=repo_root)
    record = payload.get("users", {}).get(normalized, {})
    if not isinstance(record, Mapping):
        record = {}
    return _build_lockout_state(normalized, record, now=now)


def list_login_lockout_states(
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> tuple[LoginLockoutState, ...]:
    _, payload = _load_attempt_records(path_value, env=env, repo_root=repo_root)
    states: list[LoginLockoutState] = []
    for username, record in payload.get("users", {}).items():
        if not isinstance(record, Mapping):
            continue
        state = _build_lockout_state(str(username), record, now=now)
        if state.failed_attempts <= 0 and state.locked_until is None:
            continue
        states.append(state)
    return tuple(sorted(states, key=lambda item: item.username))


def register_login_failure(
    username: str,
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> LoginLockoutState:
    normalized = _normalize_username(username)
    current = now or utc_now()
    policy = load_auth_policy(env)
    target, payload = _load_attempt_records(path_value, env=env, repo_root=repo_root)
    users = payload.setdefault("users", {})
    record = users.get(normalized, {})
    if not isinstance(record, Mapping):
        record = {}
    state = _build_lockout_state(normalized, record, now=current)

    if state.locked_until is not None and state.locked_until > current:
        return state

    reset_window = timedelta(seconds=policy.lockout_seconds)
    if state.last_failed_at is None or (current - state.last_failed_at) > reset_window:
        failed_attempts = 1
    else:
        failed_attempts = state.failed_attempts + 1
    locked_until = current + reset_window if failed_attempts >= policy.max_failed_attempts else None
    new_state = LoginLockoutState(
        username=normalized,
        failed_attempts=failed_attempts,
        locked_until=locked_until,
        last_failed_at=current,
    )
    users[normalized] = new_state.to_record()
    payload["updated_at"] = current.isoformat()
    _atomic_write_json(target, payload)
    return new_state


def clear_login_failures(
    username: str,
    path_value: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> None:
    normalized = _normalize_username(username)
    target, payload = _load_attempt_records(path_value, env=env, repo_root=repo_root)
    users = payload.setdefault("users", {})
    if normalized in users:
        users.pop(normalized, None)
        payload["updated_at"] = utc_now().isoformat()
        _atomic_write_json(target, payload)
