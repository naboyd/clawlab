#!/usr/bin/env python3
"""CLI for claw-auth user management."""

from __future__ import annotations

import argparse
import getpass
import sys

import store


def main() -> int:
    parser = argparse.ArgumentParser(description="claw-auth user management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create-user", help="Create a user")
    create.add_argument("username")
    create.add_argument(
        "--role",
        default="admin",
        choices=sorted(store.VALID_ROLES),
        help="operator, admin, or superadmin",
    )

    sub.add_parser("list-users", help="List users")

    delete = sub.add_parser("delete-user", help="Delete a user")
    delete.add_argument("username")

    passwd = sub.add_parser("set-password", help="Reset a user password")
    passwd.add_argument("username")

    email = sub.add_parser("set-webex-email", help="Link a Webex personEmail to a claw-auth user")
    email.add_argument("username")
    email.add_argument("email", nargs="?", default="", help="Webex email (empty to clear)")

    args = parser.parse_args()
    store.init_db()

    if args.cmd == "create-user":
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        try:
            store.create_user(args.username, password, args.role)
        except Exception as exc:  # noqa: BLE001
            print(exc, file=sys.stderr)
            return 1
        print(f"Created user {args.username.lower()}")
        return 0

    if args.cmd == "list-users":
        for user in store.list_users():
            status = "disabled" if user["disabled"] else "active"
            wx = user.get("webex_email") or "—"
            print(
                f"{user['username']}\t{user['role']}\t{status}\t{wx}\t{user['created_at']}"
            )
        return 0

    if args.cmd == "set-webex-email":
        try:
            store.set_webex_email(args.username, args.email)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        if (args.email or "").strip():
            print(f"Linked {args.username.lower()} → {args.email.strip().lower()}")
        else:
            print(f"Cleared Webex email for {args.username.lower()}")
        return 0

    if args.cmd == "delete-user":
        store.delete_user(args.username)
        print(f"Deleted {args.username.lower()}")
        return 0

    if args.cmd == "set-password":
        password = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        try:
            store.set_password(args.username, password)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Updated password for {args.username.lower()}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
