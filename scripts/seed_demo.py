"""Load the demo dataset through the real API.

Uploads happen via POST /upload as an authenticated data_operator, so the resulting
demo state is produced by the actual ingestion -> normalization -> validation ->
exception pipeline. Nothing is written directly to the database, which means what the
demo shows is what the product genuinely does.

Usage:
    python scripts/seed_demo.py                      # in-process, no server needed
    python scripts/seed_demo.py --url http://localhost:8000   # against a running server
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(API_ROOT))

UPLOADS = [
    ("loan_tape.csv", "loan_tape"),
    ("servicer_update.csv", "servicer_update"),
    ("document_manifest.csv", "document_manifest"),
]

OPERATOR = ("data_operator", "data_operator_dev")
REVIEWER = ("reviewer", "reviewer_dev")


def _client(url: str | None):
    """Return an httpx-compatible client, either in-process or against a live server."""
    if url:
        import httpx

        return httpx.Client(base_url=url, timeout=120.0), False

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    client.__enter__()  # run lifespan so tables exist and users are seeded
    return client, True


def _login(client, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    if response.status_code != 200:
        raise SystemExit(f"Login failed for {username}: {response.status_code} {response.text}")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Base URL of a running API. Omit to run in-process.")
    args = parser.parse_args()

    missing = [name for name, _ in UPLOADS if not (DATA_DIR / name).exists()]
    if missing:
        raise SystemExit(f"Missing demo data: {missing}. Run scripts/generate_demo_data.py first.")

    client, managed = _client(args.url)
    try:
        headers = _login(client, *OPERATOR)
        print("Uploading demo dataset as data_operator:")
        for filename, source_type in UPLOADS:
            payload = (DATA_DIR / filename).read_bytes()
            response = client.post(
                "/upload",
                data={"source_type": source_type},
                files={"file": (filename, payload, "text/csv")},
                headers=headers,
            )
            if response.status_code != 200:
                raise SystemExit(f"Upload of {filename} failed: {response.status_code} {response.text}")
            body = response.json()
            print(
                f"  {filename:<24} total={body['total_rows']:>3} "
                f"imported={body['imported_rows']:>3} failed={body['failed_rows']:>2}"
            )
            for failure in body["failed_details"]:
                print(f"      row {failure['row_number']}: {failure['reason']}")

        reviewer_headers = _login(client, *REVIEWER)
        summary = client.get("/summary", headers=reviewer_headers).json()
        print("\nResulting state:")
        print(f"  loans              {summary['loans']['total']}")
        print(f"  with open issues   {summary['loans']['with_open_exceptions']}")
        print(f"  exceptions open    {summary['exceptions']['open']}")
        print(f"  data quality score {summary['data_quality_score']}")
        print("\n  exception types:")
        for item in summary["exceptions"]["by_type"]:
            print(f"    {item['count']:>3}  {item['type']}")
        print("\nDemo data loaded. Log in as reviewer/reviewer_dev to review the queue.")
    finally:
        if managed:
            client.__exit__(None, None, None)
        else:
            client.close()


if __name__ == "__main__":
    main()
