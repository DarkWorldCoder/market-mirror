"""Workspace database admin, run on the server itself.

    python -m app.db.cli migrate                      apply pending migrations
    python -m app.db.cli status                       show applied and pending migrations
    python -m app.db.cli reset-password EMAIL         set a new password (prompted) and sign that person out
    python -m app.db.cli share-run WORKSPACE_ID RUN   let a workspace see a saved run folder
    python -m app.db.cli workspaces                   list workspaces with their owners
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import Database, database_url, get_db, repo


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.db.cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("status")
    reset = sub.add_parser("reset-password")
    reset.add_argument("email")
    share = sub.add_parser("share-run")
    share.add_argument("workspace_id")
    share.add_argument("run")
    sub.add_parser("workspaces")
    args = parser.parse_args(argv)

    if args.command == "migrate":
        db = Database(database_url())
        applied = db.migrate()
        print(json.dumps({"database": db.dialect, "applied": applied}))
        return 0
    if args.command == "status":
        db = Database(database_url())
        done = db.applied()
        print(json.dumps({"database": db.dialect,
                          "migrations": [{"version": m["version"], "name": m["name"],
                                          "applied": m["version"] in done} for m in db.migrations()]}, indent=2))
        return 0
    db = get_db()
    if args.command == "reset-password":
        from ..auth import hash_password
        password = getpass.getpass("New password (12-256 characters): ")
        if password != getpass.getpass("Repeat it: "):
            print("The passwords differ.", file=sys.stderr)
            return 1
        hashed = hash_password(password)
        with db.transaction() as conn:
            user = repo.user_by_email(conn, repo.normalize_email(args.email))
            if not user:
                print("No account uses that email.", file=sys.stderr)
                return 1
            repo.set_password(conn, user["id"], hashed)
        print("Password changed. Every browser signed in as that person is signed out.")
        return 0
    if args.command == "share-run":
        from ..api.runs import _run_dir
        _run_dir(args.run)
        with db.transaction() as conn:
            if not repo.workspace(conn, args.workspace_id):
                print("No such workspace. List them with: python -m app.db.cli workspaces", file=sys.stderr)
                return 1
            repo.add_run(conn, args.workspace_id, args.run, None)
        print(f"{args.run} is now visible in {args.workspace_id}.")
        return 0
    with db.transaction() as conn:
        rows = conn.all("SELECT w.id, w.name, u.email FROM workspaces w JOIN memberships m ON m.workspace_id=w.id "
                        "AND m.role='owner' JOIN users u ON u.id=m.user_id ORDER BY w.created_at")
    for row in rows:
        print(f"{row['id']}\t{row['name']}\t{row['email']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
