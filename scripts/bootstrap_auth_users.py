from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.services.auth import (
    AuthAccount,
    generate_temporary_password,
    hash_password,
    load_managed_auth_accounts,
    resolve_auth_users_path,
    save_managed_auth_accounts,
)


ROLE_ACCOUNT_TEMPLATES = (
    ("admin_ops", "admin", "Operations Admin", "admin_password"),
    ("safety_manager", "safety_manager", "Safety Manager", "safety_manager_password"),
    ("team_lead", "team_lead", "Team Lead", "team_lead_password"),
    ("viewer_readonly", "viewer", "Viewer Readonly", "viewer_password"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap managed console accounts for each role.")
    parser.add_argument("--output", default=None, help="Managed auth user file path. Defaults to HELMET_AUTH_USERS_FILE or artifacts/runtime/ops/auth_users.json.")
    parser.add_argument("--overwrite", action="store_true", help="Replace the managed account file instead of merging with existing accounts.")
    parser.add_argument("--admin-password", dest="admin_password", default=None, help="Password for admin_ops.")
    parser.add_argument("--safety-manager-password", dest="safety_manager_password", default=None, help="Password for safety_manager.")
    parser.add_argument("--team-lead-password", dest="team_lead_password", default=None, help="Password for team_lead.")
    parser.add_argument("--viewer-password", dest="viewer_password", default=None, help="Password for viewer_readonly.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_credentials: list[tuple[str, str, str]] = []
    managed_accounts = {} if args.overwrite else {item.username: item for item in load_managed_auth_accounts(args.output)}

    for username, role, display_name, password_arg_name in ROLE_ACCOUNT_TEMPLATES:
        plaintext_password = getattr(args, password_arg_name) or generate_temporary_password()
        managed_accounts[username] = AuthAccount(
            username=username,
            role=role,
            display_name=display_name,
            password_hash=hash_password(plaintext_password),
        )
        generated_credentials.append((username, role, plaintext_password))

    output_path = save_managed_auth_accounts(tuple(managed_accounts.values()), args.output)
    resolved_path = resolve_auth_users_path(args.output)

    print(f"managed_users_path={resolved_path}")
    print(f"saved_accounts={len(managed_accounts)}")
    for username, role, plaintext_password in generated_credentials:
        print(f"{username}|{role}|{plaintext_password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
