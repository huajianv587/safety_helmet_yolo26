from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.sync_person_registry as sync_person_registry


class _FakeExecuteBuilder:
    def __init__(self, client, payload):
        self.client = client
        self.payload = payload

    def execute(self):
        self.client.calls.append(self.payload)
        missing = self.client.missing_columns[len(self.client.calls) - 1] if len(self.client.calls) - 1 < len(self.client.missing_columns) else None
        if missing:
            raise RuntimeError(f"Could not find the '{missing}' column of 'persons' in the schema cache")
        return {"status": "ok"}


class _FakeTable:
    def __init__(self, client):
        self.client = client

    def upsert(self, payload, on_conflict=None):
        assert on_conflict == "person_id"
        return _FakeExecuteBuilder(self.client, payload)


class _FakeClient:
    def __init__(self, missing_columns):
        self.missing_columns = list(missing_columns)
        self.calls = []

    def table(self, name):
        assert name == "persons"
        return _FakeTable(self)


class SyncPersonRegistryTest(unittest.TestCase):
    def test_sync_people_retries_without_missing_columns(self) -> None:
        payload = [
            {
                "person_id": "person-001",
                "name": "Shift Lead",
                "aliases": ["Lead A"],
                "badge_keywords": ["SHIFT"],
            }
        ]
        client = _FakeClient(["aliases", "badge_keywords", None])

        ignored = sync_person_registry._sync_people(client, payload)

        self.assertEqual(ignored, {"aliases", "badge_keywords"})
        self.assertEqual(client.calls[-1], [{"person_id": "person-001", "name": "Shift Lead"}])


if __name__ == "__main__":
    unittest.main()
