#!/usr/bin/env python3
"""SOWKNOW host-health watch — the control that was missing on 2026-09-26.

WHY THIS EXISTS. On 2026-09-26 the host reached **14,119 zombie processes, 100% swap,
load 6.5 and 17,585 processes** over a 17-day uptime. Nobody was paged. In the same
window sowknow's search degraded progressively (slow streams at 01:17, 03:17, 04:35,
05:47, 08:02, 09:17, 10:35) and only a **reboot at 11:18** cleared it. Two apps looked
"broken" for hours and the condition was fully visible the entire time — to nobody.

`guardian-hc` covers CONTAINER health (tcp/http/container checks + self-healing). It does
not look at the HOST. This closes that gap and nothing more: swap, zombies, and container
restarts/OOM kills.

ALERT ON TRANSITION, NOT ON EVERY CHECK. A standing condition fails every run; sending
every run is how a channel becomes noise, and noise is a slower form of silence (the
lesson the E2E probe already had to learn). So: alert when a check ENTERS failure, one
reminder per COOLDOWN_HOURS, and one recovery notice so the channel closes the loop.

FLOOD/AUDIT DISCIPLINE. Creds are read from .env and never printed. The state file
records only the last alert time per check, so a restart of this script cannot silence a
standing fault.

Cron (every 15 min, matching the search smoke test):
  */15 * * * * /home/development/src/active/sowknow4/scripts/host_health_watch.py \
      >> /var/log/sowknow-host-health.log 2>&1

Exit code is always 0: cron's MAILTO is empty on this host, so a non-zero exit would be
mailed nowhere and would only look like a failure in the log. The ALERT is the signal.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, "..", ".env")
LOG = "/var/log/sowknow-host-health.log"
STATE = "/var/lib/sowknow-host-health.json"
COOLDOWN_HOURS = 6

# Thresholds. Chosen from the 2026-09-26 incident, not from taste: the host was at 100%
# swap and >14k zombies while still "healthy" by every container check.
SWAP_PCT_MAX = 50.0      # was 100% during the incident
ZOMBIE_MAX = 100         # was 14,119; a handful is normal
RESTART_DELTA_MAX = 3    # container restarts between consecutive runs


def env(key: str) -> str:
    try:
        with open(ENV_FILE) as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


DRY_RUN = "--dry-run" in sys.argv


def alert(msg: str) -> None:
    """Same channel and shape as the search smoke test.

    --dry-run prints instead of sending: an alert path that can only be exercised by paging
    production is an alert path that never gets tested (golegal's probe learned this and
    added PROBE_ALERT_DRY_RUN for the same reason).
    """
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_ADMIN_CHAT_ID")
    if DRY_RUN:
        log(f"DRY-RUN would alert (creds {'present' if token and chat else 'ABSENT'}): {msg}")
        return
    if not (token and chat):
        log("WARN cannot alert: telegram creds absent")
        return
    import urllib.request
    data = json.dumps({"chat_id": chat, "text": f"\U0001F534 SOWKNOW host health\n{msg}"}).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"WARN alert send failed: {type(e).__name__}")


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def load_state() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f:
            json.dump(s, f)
    except OSError as e:
        log(f"WARN cannot persist state: {e}")


def swap_pct() -> float:
    out = sh("free -m | awk '/^Swap:/{if ($2>0) printf \"%.1f\", $3/$2*100; else print 0}'")
    try:
        return float(out or 0)
    except ValueError:
        return 0.0


def zombies() -> int:
    try:
        return int(sh("ps -eo stat | grep -c Z") or 0)
    except ValueError:
        return 0


def container_restarts() -> dict:
    names = sh("docker ps -a --format '{{.Names}}'").split()
    out = {}
    for n in names:
        v = sh(f"docker inspect --format '{{{{.RestartCount}}}}' {n}")
        try:
            out[n] = int(v)
        except ValueError:
            pass
    return out


def oomkilled() -> list:
    names = sh("docker ps -a --format '{{.Names}}'").split()
    return [n for n in names
            if sh(f"docker inspect --format '{{{{.State.OOMKilled}}}}' {n}").strip() == "true"]


def main() -> int:
    now = time.time()
    state = load_state()
    prev = state.get("last_alert", {})
    prev_restarts = state.get("restarts", {})

    findings = []

    if "--simulate" in sys.argv:
        # Exercises the ALERT path without waiting for a real fault. Without this the only
        # way to prove it works is to let the host degrade again.
        findings.append(("swap", f"SIMULATED: swap at 99.0% (> {SWAP_PCT_MAX:.0f}%)"))
        log("SIMULATED finding injected")

    sp = swap_pct()
    if sp > SWAP_PCT_MAX:
        findings.append(("swap", f"swap at {sp:.1f}% (> {SWAP_PCT_MAX:.0f}%) — the host was at 100% when two apps degraded on 2026-09-26"))

    z = zombies()
    if z > ZOMBIE_MAX:
        findings.append(("zombies", f"{z} zombie processes (> {ZOMBIE_MAX}) — check which container's PID 1 is not reaping"))

    oom = oomkilled()
    if oom:
        findings.append(("oom", f"OOMKilled containers: {', '.join(oom[:5])}"))

    cur_restarts = container_restarts()
    bumped = []
    for n, c in cur_restarts.items():
        p = prev_restarts.get(n)
        if p is not None and c - p >= RESTART_DELTA_MAX:
            bumped.append(f"{n}(+{c - p})")
    if bumped:
        findings.append(("restarts", "container restart spike: " + ", ".join(bumped[:6])))

    # alert on transition, then at most once per cooldown; announce recovery
    active = {k: m for k, m in findings}
    for key, msg in active.items():
        last = float(prev.get(key, 0))
        if now - last >= COOLDOWN_HOURS * 3600:
            alert(msg)
            prev[key] = now
            log(f"ALERT [{key}] {msg}")
        else:
            log(f"suppressed [{key}] {msg}")

    for key in list(prev):
        if key not in active and key in ("swap", "zombies", "oom", "restarts"):
            alert(f"RECOVERED: {key} is back within threshold")
            log(f"RECOVERED [{key}]")
            prev.pop(key, None)

    if not findings:
        log(f"OK swap={sp:.1f}% zombies={z} restarts_tracked={len(cur_restarts)}")

    state["last_alert"] = prev
    state["restarts"] = cur_restarts
    save_state(state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # a broken watch must never look like a healthy host
        log(f"ERROR {type(e).__name__}: {e}")
        alert(f"host-health watch itself failed: {type(e).__name__}: {e}")
        sys.exit(0)
