"""Reset one account's password, in place, on the box that holds the database.

This exists because there is no self-service reset. A real "forgot password"
flow needs a channel to prove the account is yours — an email or an SMS — and
this project has no mail sender and no SMS vendor, so there is nothing to send a
link over. Adding one is a product decision with a new dependency and a new
secret; until it is made, the only honest recovery is an operator with access to
the database, and the only honest thing to do about that is to make the operator
path explicit and safe rather than leaving it to be improvised.

Run it where the SQLite file lives, which on Render means the service Shell:

    cd /app && runuser --preserve-environment -u pwuser -- \
        python scripts/reset_password.py you@example.com

``runuser`` matters. The image's Shell is root while the app runs as ``pwuser``
(see the Dockerfile), and SQLite writing as root leaves root-owned ``-wal`` and
``-shm`` files beside the database that the app then cannot write — turning a
password reset into an outage. If you already ran it as root, fix it with
``chown pwuser:pwuser /var/data/marketing_agent.db*``.

The new password is read from the terminal and never echoed, never passed as an
argument, and never written to shell history. It goes through ``server.auth``
and ``server.db`` rather than hand-written SQL, so the stored hash is produced
exactly the way registration produces it.
"""
from __future__ import annotations

import getpass
import os
import sys

# Run from the project root. Invoked by path from elsewhere, sys.path[0] is the
# script's own directory and `server` is not importable, so put the working
# directory on the path too.
sys.path.insert(0, os.getcwd())

from server import auth, db  # noqa: E402 — after the path fix, deliberately


def read_new_password() -> str:
    """From the tty when there is one, stdin when there is not (for tests)."""
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("New password (8-128 chars, not echoed): ")
    again = getpass.getpass("Again: ")
    if first != again:
        sys.exit("The two entries differ. Nothing was changed.")
    return first


def main() -> None:
    account = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not account:
        sys.exit("Usage: python scripts/reset_password.py <account-email-or-phone>")

    print(f"database: {db.DB_PATH}")
    # The login route lowercases an email before looking it up; match that, or a
    # capitalised address reports "no such account" against a row sitting there.
    user = db.get_user_by_account(account.lower() if "@" in account else account)
    if user is None:
        sys.exit(f"No account {account!r} in this database. Nothing was changed.")
    print(f"account:  {user['account']} ({user['username']})")

    password = read_new_password()
    try:
        # The same validator the registration route uses, so a password this
        # script accepts is one the login form will also accept.
        password = auth.validate_password(password)
    except Exception as exc:  # noqa: BLE001 — HTTPException carries the reason
        sys.exit(f"Rejected: {getattr(exc, 'detail', exc)}")

    if db.update_user_profile(user["id"],
                              password_hash=auth.hash_password(password)) is None:
        sys.exit("The update matched no row. Nothing was changed.")

    # Read it back through the check the login route runs, so this cannot report
    # success on a hash that will not actually verify.
    fresh = db.get_user_by_account(user["account"])
    if not auth.verify_password(password, fresh["password_hash"]):
        sys.exit("Wrote a hash that does not verify — stop and investigate "
                 "before trying to log in.")
    print("done: the new password verifies against the stored hash.")


if __name__ == "__main__":
    main()
