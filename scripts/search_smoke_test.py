#!/usr/bin/env python3
"""SOWKNOW search smoke test — runs every 15 min via cron.

Catches the exact failure classes of the 2026-07-28 P0:
  1. search/health not healthy (embed server / circuit breaker)
  2. stream returns no results or takes > 60s (invalid index / plan cliff)
  3. bogus relevance: "Liste" must surface list-titled docs (calibration)
  4. suggest fuzzy path 500/503 (documents.title regression)
  5. intent fallback storm: French query must not parse as language "en"

Alerts via Telegram on failure (creds from .env, never printed).
Log: /var/log/sowknow-search-smoke.log
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

API = "http://127.0.0.1:8001"
LOG = "/var/log/sowknow-search-smoke.log"
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def env(key: str) -> str:
    try:
        with open(ENV_FILE) as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def alert(msg: str) -> None:
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_ADMIN_CHAT_ID")
    if not (token and chat):
        return
    try:
        data = json.dumps({"chat_id": chat, "text": f"🔴 SOWKNOW search smoke test\n{msg}"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def mint_token() -> str:
    out = subprocess.run(
        ["docker", "exec", "-i", "sowknow-backend", "python", "-c",
         "from app.utils.security import create_access_token\n"
         "print(create_access_token({'sub': 'msow@gollamsys.com'}))"],
        capture_output=True, text=True, timeout=60,
    )
    return out.stdout.strip().splitlines()[-1]


def http(method: str, path: str, token: str, body: dict | None = None, timeout: int = 90) -> tuple[int, str]:
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode()


def parse_sse(text: str) -> dict:
    events = {}
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                try:
                    events[ev] = json.loads(line[6:])
                except Exception:
                    pass
    return events


def main() -> int:
    # Skip during declared maintenance windows (migrations, index builds)
    if os.path.exists("/tmp/sowknow_maintenance"):
        log("SKIP: maintenance flag present")
        return 0
    failures = []
    token = mint_token()
    if not token:
        log("FAIL: could not mint token")
        alert("cannot mint auth token — backend or user lookup broken")
        return 1

    # 1. search health
    try:
        status, body = http("GET", "/api/v1/search/health", token)
        if '"status":"healthy"' not in body.replace(" ", ""):
            failures.append(f"search/health not healthy: {body[:120]}")
    except Exception as e:
        failures.append(f"search/health unreachable: {e}")

    # 2+3. stream checks
    for query, expect_in_title in [("Liste", "liste"), ("contrat", None)]:
        try:
            t0 = time.monotonic()
            _, raw = http("POST", "/api/v1/search/stream", token,
                          {"query": query, "mode": "auto", "limit": 8}, timeout=90)
            elapsed = time.monotonic() - t0
            ev = parse_sse(raw)
            if "error" in ev:
                failures.append(f"stream '{query}' error event: {str(ev['error'])[:100]}")
            done = ev.get("done", {})
            results = ev.get("results", {}).get("results", [])
            if not results:
                failures.append(f"stream '{query}' returned 0 results")
            if elapsed > 60:
                failures.append(f"stream '{query}' took {elapsed:.0f}s (>60s)")
            if expect_in_title and not any(expect_in_title in r.get("document_title", "").lower() for r in results):
                failures.append(f"stream '{query}': no '{expect_in_title}' doc in top {len(results)} (relevance regression)")
            # 5. intent must not be the dumb fallback for a French query
            intent = ev.get("intent", {})
            if query == "contrat" and intent.get("language") == "en":
                failures.append("intent fallback for French query (LLM intent parse broken)")
        except Exception as e:
            failures.append(f"stream '{query}' failed: {str(e)[:120]}")

    # 4. suggest fuzzy path (503 regression)
    try:
        status, _ = http("GET", "/api/v1/search/suggest?q=zzqx", token)
        if status != 200:
            failures.append(f"suggest fuzzy HTTP {status}")
    except Exception as e:
        failures.append(f"suggest fuzzy failed: {str(e)[:100]}")

    if failures:
        for f in failures:
            log(f"FAIL: {f}")
        alert("\n".join(f"• {f}" for f in failures[:6]))
        return 1
    log("OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
