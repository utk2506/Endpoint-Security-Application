"""
create_admin.py — Create an admin or viewer user for the Admin Control System.

Usage:
    python create_admin.py <username> <password> [--role admin|viewer]
"""

import sys
import os
import argparse

# Add the server directory to path so we can import models
sys.path.append(os.path.join(os.path.dirname(__file__), 'server'))

from models import SessionLocal, User  # type: ignore
from app import get_password_hash  # type: ignore


def create_user(username: str, password: str, role: str):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"[ERROR] User '{username}' already exists.")
            sys.exit(1)

        hashed = get_password_hash(password)
        user = User(username=username, hashed_password=hashed, is_active=True, role=role)
        db.add(user)
        db.commit()
        print(f"[OK] User '{username}' created with role '{role}'.")
    except Exception as e:
        print(f"[ERROR] {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a portal user")
    parser.add_argument("username", help="Username")
    parser.add_argument("password", help="Password")
    parser.add_argument("--role", default="admin", choices=["admin", "viewer"],
                        help="User role: admin (default) or viewer (read-only)")
    args = parser.parse_args()
    create_user(args.username, args.password, args.role)
