from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.services.auth import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a PBKDF2 password hash for the Safety Helmet console.")
    parser.add_argument("--password", help="Plaintext password to hash. If omitted, an interactive prompt is used.")
    args = parser.parse_args()

    password = args.password
    if not password:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Confirm Password: ")
        if first != second:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        password = first

    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
