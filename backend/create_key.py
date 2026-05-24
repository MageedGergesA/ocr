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

        key = models.ApiKey(user_id=user.id)
        db.add(key)
        db.commit()
        db.refresh(key)

        print(f"user : {user.email}  (plan: {user.plan})")
        print(f"key  : {key.key}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
