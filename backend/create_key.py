"""Mint an API key for a customer.

Run from the backend/ directory:
    ../venv/bin/python create_key.py --email someone@example.com --plan starter
"""
import argparse

from app import models
from app.db import SessionLocal, init_db


def main():
    parser = argparse.ArgumentParser(description="Create a user + API key")
    parser.add_argument("--email", required=True)
    parser.add_argument("--plan", default="free",
                        choices=["free", "starter", "pro", "business"])
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(email=args.email).first()
        if user:
            user.plan = args.plan
        else:
            user = models.User(email=args.email, plan=args.plan)
            db.add(user)
        db.commit()
        db.refresh(user)

        key, raw = models.new_api_key(user.id)
        db.add(key)
        db.commit()

        print(f"user : {user.email}  (plan: {user.plan})")
        print(f"key  : {raw}   (stored hashed — copy it now, it is not recoverable)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
