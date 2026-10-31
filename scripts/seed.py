"""Seed synthetic doctors, schedules and patients: uv run python scripts/seed.py"""

from medagent.db.seed import seed
from medagent.db.session import get_sessionmaker


def main() -> None:
    with get_sessionmaker()() as session:
        created = seed(session)
    print("Seeded:", ", ".join(f"{n} {k}" for k, n in created.items()))


if __name__ == "__main__":
    main()
