from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.services.auth import (
    AuthAccount,
    auth_configuration_summary,
    authenticate_user,
    clear_login_failures,
    get_login_lockout_state,
    hash_password,
    load_auth_accounts,
    load_managed_auth_accounts,
    register_login_failure,
    role_has_permission,
    save_managed_auth_accounts,
    verify_password,
)


class AuthServiceTest(unittest.TestCase):
    def test_hash_password_round_trip(self) -> None:
        password_hash = hash_password("StrongPass!2026")
        self.assertTrue(verify_password("StrongPass!2026", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))

    def test_load_bootstrap_admin_from_env(self) -> None:
        env = {
            "HELMET_AUTH_ADMIN_USERNAME": "admin",
            "HELMET_AUTH_ADMIN_PASSWORD_HASH": hash_password("AdminPass!2026"),
            "HELMET_AUTH_ADMIN_DISPLAY_NAME": "Safety Admin",
            "HELMET_AUTH_ADMIN_ROLE": "admin",
        }
        accounts = load_auth_accounts(env)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].username, "admin")
        self.assertEqual(accounts[0].role, "admin")
        self.assertEqual(accounts[0].display_name, "Safety Admin")

    def test_load_bootstrap_admin_accepts_docker_escaped_hash(self) -> None:
        env = {
            "HELMET_AUTH_ADMIN_USERNAME": "admin",
            "HELMET_AUTH_ADMIN_PASSWORD_HASH": hash_password("AdminPass!2026").replace("$", "$$"),
            "HELMET_AUTH_ADMIN_ROLE": "admin",
        }
        identity = authenticate_user("admin", "AdminPass!2026", env)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.role, "admin")

    def test_authenticate_user_accepts_json_accounts(self) -> None:
        env = {
            "HELMET_AUTH_USERS_JSON": json.dumps(
                [
                    {
                        "username": "lead",
                        "display_name": "Shift Lead",
                        "role": "team_lead",
                        "password_hash": hash_password("LeadPass!2026"),
                    }
                ]
            )
        }
        identity = authenticate_user("lead", "LeadPass!2026", env)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.username, "lead")
        self.assertEqual(identity.role, "team_lead")
        self.assertIsNone(authenticate_user("lead", "bad-pass", env))

    def test_auth_configuration_summary_reports_roles(self) -> None:
        env = {
            "HELMET_AUTH_USERS_JSON": json.dumps(
                [
                    {
                        "username": "viewer01",
                        "role": "viewer",
                        "password_hash": hash_password("ViewerPass!2026"),
                    }
                ]
            )
        }
        summary = auth_configuration_summary(env)
        self.assertTrue(summary["configured"])
        self.assertEqual(summary["enabled_users"], 1)
        self.assertEqual(summary["roles"], ("viewer",))

    def test_managed_accounts_can_be_saved_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {"HELMET_AUTH_USERS_FILE": str(Path(temp_dir) / "auth_users.json")}
            save_managed_auth_accounts(
                (
                    AuthAccount(
                        username="manager01",
                        role="safety_manager",
                        display_name="Safety Manager 01",
                        password_hash=hash_password("ManagerPass!2026"),
                    ),
                ),
                env=env,
            )
            accounts = load_managed_auth_accounts(env=env)
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].username, "manager01")
            self.assertEqual(accounts[0].source, "managed_file")

    def test_login_failures_trigger_and_clear_lockout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "HELMET_AUTH_ATTEMPTS_FILE": str(Path(temp_dir) / "auth_attempts.json"),
                "HELMET_AUTH_MAX_FAILED_ATTEMPTS": "3",
                "HELMET_AUTH_LOCKOUT_SECONDS": "120",
            }
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            register_login_failure("viewer01", env=env, now=now)
            register_login_failure("viewer01", env=env, now=now)
            locked_state = register_login_failure("viewer01", env=env, now=now)
            self.assertEqual(locked_state.failed_attempts, 3)
            self.assertGreater(locked_state.remaining_seconds(now=now), 0)
            clear_login_failures("viewer01", env=env)
            cleared_state = get_login_lockout_state("viewer01", env=env, now=now)
            self.assertEqual(cleared_state.failed_attempts, 0)
            self.assertEqual(cleared_state.remaining_seconds(now=now), 0)

    def test_role_permissions_match_console_expectations(self) -> None:
        self.assertTrue(role_has_permission("admin", "camera.edit"))
        self.assertTrue(role_has_permission("admin", "account.manage"))
        self.assertTrue(role_has_permission("safety_manager", "review.assign"))
        self.assertFalse(role_has_permission("viewer", "review.update"))


if __name__ == "__main__":
    unittest.main()
