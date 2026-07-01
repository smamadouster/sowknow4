#!/usr/bin/env python3
"""
Check recently uploaded SOWKNOW documents and their processing status.

Usage:
    python3 check_uploads.py --email you@example.com --password yourpass
    python3 check_uploads.py --bot-key YOUR_BOT_API_KEY
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

SOWKNOW_URL = os.getenv("SOWKNOW_URL", "https://sowknow.gollamtech.com").rstrip("/")


def login(email: str, password: str) -> Optional[requests.Session]:
    session = requests.Session()
    resp = session.post(
        f"{SOWKNOW_URL}/api/v1/auth/login",
        data={"username": email, "password": password},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} {resp.text[:200]}")
        return None
    token = session.cookies.get("access_token")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def bot_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers["X-Bot-Api-Key"] = api_key
    return session


def list_documents(session: requests.Session, hours: int = 24) -> list[dict]:
    resp = session.get(
        f"{SOWKNOW_URL}/api/v1/documents",
        params={"page": 1, "page_size": 100, "sort": "-created_at"},
        timeout=30,
    )
    if not resp.ok:
        print(f"Failed to list documents: {resp.status_code} {resp.text[:200]}")
        return []

    data = resp.json()
    items = data.get("items", data.get("documents", []))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for doc in items:
        created = doc.get("created_at") or doc.get("created")
        if created:
            try:
                # Handle ISO strings with or without Z
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                created_dt = datetime.min.replace(tzinfo=timezone.utc)
        else:
            created_dt = datetime.min.replace(tzinfo=timezone.utc)
        if created_dt >= cutoff:
            recent.append(doc)
    return recent


def get_document(session: requests.Session, doc_id: str) -> Optional[dict]:
    resp = session.get(f"{SOWKNOW_URL}/api/v1/documents/{doc_id}", timeout=30)
    if not resp.ok:
        return None
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Check SOWKNOW upload status")
    parser.add_argument("--email", help="SOWKNOW login email")
    parser.add_argument("--password", help="SOWKNOW login password")
    parser.add_argument("--bot-key", help="BOT_API_KEY (internal upload key)")
    parser.add_argument("--hours", type=int, default=24, help="How far back to look (default: 24)")
    args = parser.parse_args()

    if args.bot_key:
        session = bot_session(args.bot_key)
        # Bot key alone cannot list documents — it only uploads.
        print("Note: BOT_API_KEY can upload but cannot list documents.")
        print("      Use --email + --password to see processing status.")
        return

    email = args.email or os.getenv("SOWKNOW_EMAIL")
    password = args.password or os.getenv("SOWKNOW_PASSWORD")

    if not email or not password:
        print("Provide --email + --password or set SOWKNOW_EMAIL / SOWKNOW_PASSWORD")
        sys.exit(1)

    session = login(email, password)
    if not session:
        sys.exit(1)

    docs = list_documents(session, hours=args.hours)
    if not docs:
        print(f"No documents found in the last {args.hours} hours.")
        return

    print(f"\nFound {len(docs)} document(s) in the last {args.hours} hours:\n")
    print(f"{'ID':<36} {'Filename':<30} {'Bucket':<12} {'Status':<12} {'Stage':<16} {'Created'}")
    print("-" * 130)

    status_counts = {}
    for doc in docs:
        doc_id = str(doc.get("id", ""))
        filename = (doc.get("original_filename") or doc.get("filename", ""))[:30]
        bucket = doc.get("bucket", "?")
        status = doc.get("status", "?")
        stage = doc.get("pipeline_stage", "?")
        created = (doc.get("created_at") or doc.get("created", ""))[:19]
        status_counts[status] = status_counts.get(status, 0) + 1
        print(f"{doc_id:<36} {filename:<30} {bucket:<12} {status:<12} {stage:<16} {created}")

    print("\nStatus summary:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # Flag documents that are stuck
    stuck = [d for d in docs if d.get("status") in ("error", "pending") or d.get("pipeline_stage") == "failed"]
    if stuck:
        print("\n⚠️  Documents needing attention:")
        for doc in stuck:
            doc_id = doc.get("id", "")
            detail = get_document(session, doc_id) or doc
            error = detail.get("pipeline_error") or detail.get("error_message") or "no error message"
            print(f"  - {detail.get('original_filename') or detail.get('filename')} ({detail.get('status')}/{detail.get('pipeline_stage')}): {error}")
    else:
        print("\n✅ No stuck/error documents in the recent batch.")


if __name__ == "__main__":
    main()
