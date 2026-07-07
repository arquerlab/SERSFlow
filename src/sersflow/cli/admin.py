from __future__ import annotations

import argparse
import sys

from sersflow.infra.auth_store import create_user, set_superuser
from sersflow.infra.migration_store import assign_orphans


def _cmd_create_user(args: argparse.Namespace) -> int:
    try:
        user = create_user(
            username=args.username,
            password=args.password,
            is_superuser=bool(args.superuser),
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    role = "superuser" if user.is_superuser else "user"
    print(f"created {role} {user.username} ({user.user_id})")
    return 0


def _cmd_grant_superuser(args: argparse.Namespace) -> int:
    try:
        user = set_superuser(username=args.username, superuser=True)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"granted superuser to {user.username} ({user.user_id})")
    return 0


def _cmd_revoke_superuser(args: argparse.Namespace) -> int:
    try:
        user = set_superuser(username=args.username, superuser=False)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"revoked superuser from {user.username} ({user.user_id})")
    return 0


def _cmd_assign_orphans(args: argparse.Namespace) -> int:
    from sersflow.infra.auth_store import get_user_by_id, get_user_by_username

    user = get_user_by_username(args.username) or get_user_by_id(args.username)
    if user is None:
        print(f"error: user not found: {args.username}", file=sys.stderr)
        return 1
    try:
        report = assign_orphans(owner_user_id=user.user_id, dry_run=bool(args.dry_run))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    prefix = "[dry-run] " if args.dry_run else ""
    print(
        f"{prefix}datasets={report.datasets_updated} pipelines={report.pipelines_updated} "
        f"registry={report.registry_rows_updated} unloaded={report.unloaded_rows_updated}"
    )
    if report.path_only_datasets:
        print("path-only datasets without registry entry (manual review):")
        for ds_id in report.path_only_datasets:
            print(f"  - {ds_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sersflow-admin")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="Create a username/password user")
    create.add_argument("username")
    create.add_argument("password")
    create.add_argument(
        "--superuser",
        action="store_true",
        help="Grant global access to all users' data",
    )
    create.set_defaults(func=_cmd_create_user)

    grant = sub.add_parser("grant-superuser", help="Grant global access to an existing user")
    grant.add_argument("username")
    grant.set_defaults(func=_cmd_grant_superuser)

    revoke = sub.add_parser("revoke-superuser", help="Remove global access from a user")
    revoke.add_argument("username")
    revoke.set_defaults(func=_cmd_revoke_superuser)

    assign = sub.add_parser("assign-orphans", help="Assign NULL owners to a user")
    assign.add_argument("username", help="Target user_id or username is resolved via user_id field")
    assign.add_argument("--dry-run", action="store_true")
    assign.set_defaults(func=_cmd_assign_orphans)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
