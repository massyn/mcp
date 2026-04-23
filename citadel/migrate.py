"""Migrate local SQLite database to Turso."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from db import LocalDatabase, TursoDatabase

load_dotenv(Path(__file__).parent / ".env")

BATCH_SIZE = 50


async def migrate(yes: bool) -> None:
    # -- Source --
    db_env = os.environ.get("DB_PATH")
    db_path = Path(db_env).expanduser().resolve() if db_env else Path.home() / ".citadel" / "citadel.db"

    if not db_path.exists():
        print(f"Source database not found: {db_path}")
        sys.exit(1)

    # -- Target --
    turso_url = os.environ.get("TURSO_URL")
    turso_token = os.environ.get("TURSO_TOKEN")

    if not turso_url or not turso_token:
        print("TURSO_URL and TURSO_TOKEN must be set in .env")
        sys.exit(1)

    source = LocalDatabase(db_path)
    target = TursoDatabase(turso_url, turso_token)

    # -- Read source --
    rooms = await source.query("SELECT * FROM rooms ORDER BY created_on")
    entries = await source.query("SELECT * FROM entries ORDER BY created_on")

    print(f"Source : {db_path}")
    print(f"Target : {turso_url}")
    print(f"Rooms  : {len(rooms)}")
    print(f"Entries: {len(entries)}")
    print()

    if not rooms and not entries:
        print("Nothing to migrate.")
        return

    if not yes:
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    # -- Schema --
    print("Initialising schema on target...")
    await target.init_schema()

    # -- Rooms --
    print(f"Migrating {len(rooms)} room(s)...")
    for room in rooms:
        await target.execute(
            "INSERT OR IGNORE INTO rooms (name, tags, created_on, updated_on) VALUES (?, ?, ?, ?)",
            (room["name"], room["tags"], room["created_on"], room["updated_on"]),
        )
        print(f"  {room['name']}")

    # -- Entries (batched) --
    print(f"Migrating {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}...")
    for i in range(0, len(entries), BATCH_SIZE):
        batch = entries[i : i + BATCH_SIZE]
        await target.batch([
            (
                "INSERT OR IGNORE INTO entries "
                "(id, room, title, summary, detail, tags, status, created_on, updated_on) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    e["id"], e["room"], e["title"], e["summary"],
                    e["detail"], e["tags"], e["status"],
                    e["created_on"], e["updated_on"],
                ),
            )
            for e in batch
        ])
        for e in batch:
            print(f"  [{e['room']}] {e['title']}")

    await target.close()

    print()
    print(f"Done — {len(rooms)} room(s) and {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} copied.")
    print("Existing records in Turso were left unchanged (INSERT OR IGNORE).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate local Citadel SQLite database to Turso")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()
    asyncio.run(migrate(yes=args.yes))
