from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from typing import Mapping


PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
DEFAULT_HASH_ITERATIONS = 390_000

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"review.assign", "review.update", "camera.edit"}),
    "safety_manager": frozenset({"review.assign", "review.update"}),
    "team_lead": frozenset({"review.assign", "review.update"}),
    "viewer": frozenset(),
}


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

    def to_identity(self) -> TrustedIdentity:
        return TrustedIdentity(
            username=self.username,
            role=self.role,
            display_name=self.display_name,
            email=self.email,
        )


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


def role_has_permission(role: str | None, permission: str) -> bool:
    normalized = _normalize_role(role)
    return permission in ROLE_PERMISSIONS.get(normalized, frozenset())


def require_permission(role: str | None, permission: str) -> None:
    if not role_has_permission(role, permission):
        raise PermissionError(f"Role '{_normalize_role(role)}' is not allowed to perform '{permission}'.")


def _account_from_payload(payload: Mapping[str, object]) -> AuthAccount | None:
    username = _normalize_username(str(payload.get("username", "")))
    password_hash = str(payload.get("password_hash") or "").strip()
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
    )


def _load_accounts_from_json(raw_value: str) -> list[AuthAccount]:
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
        account = _account_from_payload(item)
        if account is not None:
            accounts.append(account)
    return accounts


def _load_bootstrap_admin(env: Mapping[str, str]) -> AuthAccount | None:
    username = _normalize_username(env.get("HELMET_AUTH_ADMIN_USERNAME", ""))
    password_hash = str(env.get("HELMET_AUTH_ADMIN_PASSWORD_HASH", "")).strip()
    if not username or not password_hash:
        return None
    if _parse_password_hash(password_hash) is None:
        return None
    role = _normalize_role(env.get("HELMET_AUTH_ADMIN_ROLE", "admin"), default="admin")
    display_name = str(env.get("HELMET_AUTH_ADMIN_DISPLAY_NAME", "")).strip() or _display_name_from_username(username)
    email = str(env.get("HELMET_AUTH_ADMIN_EMAIL", "")).strip()
    return AuthAccount(
        username=username,
        role=role,
        display_name=display_name,
        password_hash=password_hash,
        email=email,
    )


def load_auth_accounts(env: Mapping[str, str] | None = None) -> tuple[AuthAccount, ...]:
    raw_env = env if env is not None else os.environ
    by_username: dict[str, AuthAccount] = {}

    raw_users_json = str(raw_env.get("HELMET_AUTH_USERS_JSON", "")).strip()
    if raw_users_json:
        for account in _load_accounts_from_json(raw_users_json):
            by_username[account.username] = account

    bootstrap_admin = _load_bootstrap_admin(raw_env)
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
    accounts = load_auth_accounts(env)
    roles = tuple(sorted({account.role for account in accounts}))
    return {
        "configured": bool(accounts),
        "enabled_users": len(accounts),
        "roles": roles,
        "has_admin": any(account.role == "admin" for account in accounts),
    }
