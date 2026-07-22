"""
verify_user_email.py — set email_verified=true for a given user account.

Useful when an existing user is locked out after the email_verified column
was added (migration 006) or after a rebuild that defaulted the flag to false.

Usage:
    python -m scripts.verify_user_email user@example.com

Required env var:
    DATABASE_URL   e.g. postgresql://user:pass@host:5432/db
"""

import argparse
import logging
import os
import sys

from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark a user's email as verified in the database"
    )
    parser.add_argument("email", help="Email address of the user to verify")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without committing",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Import app modules after DATABASE_URL is loaded from the environment.
    from app.database import SessionLocal
    from app.models.user import User

    email = args.email.strip().lower()

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

        if not user:
            logger.error(f"User not found: {email}")
            sys.exit(1)

        if user.email_verified:
            logger.info(f"User already verified: {email}")
            sys.exit(0)

        if args.dry_run:
            logger.info(f"Would verify email for user: {email}")
            return

        user.email_verified = True
        db.commit()
        logger.info(f"Email verified successfully for user: {email}")


if __name__ == "__main__":
    main()
