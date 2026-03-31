from __future__ import annotations

import json
import random
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = REPO_ROOT / "configs" / "person_registry.json"


def build_people(count: int = 30) -> list[dict]:
    random.seed(20260331)
    surnames = ["Zhang", "Li", "Wang", "Liu", "Chen", "Yang", "Zhao", "Huang", "Zhou", "Wu"]
    given_names = [
        "Wei", "Lei", "Jian", "Ming", "Tao", "Gang", "Hao", "Peng", "Chao", "Bo",
        "Na", "Yan", "Xin", "Qiang", "Yong", "Jun", "Bin", "Lin", "Ting", "Yu",
    ]
    departments = ["Safety", "Production", "Mechanical", "Electrical", "Logistics"]
    teams = ["Shift A", "Shift B", "Shift C", "Maintenance", "Inspection"]
    roles = ["Worker", "Inspector", "Foreman", "Technician", "Safety Officer"]

    people: list[dict] = []
    for index in range(1, count + 1):
        name = f"{random.choice(surnames)} {random.choice(given_names)}"
        people.append(
            {
                "person_id": f"person-{index:03d}",
                "name": name,
                "employee_id": f"E{10000 + index}",
                "department": random.choice(departments),
                "team": random.choice(teams),
                "role": random.choice(roles),
                "phone": f"138{random.randint(10000000, 99999999)}",
                "face_photo_url": None,
                "badge_photo_url": None,
                "status": "active",
            }
        )
    return people


def main() -> None:
    people = build_people(30)
    TARGET_PATH.write_text(json.dumps(people, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated_people={len(people)}")
    print(f"path={TARGET_PATH}")


if __name__ == "__main__":
    main()

