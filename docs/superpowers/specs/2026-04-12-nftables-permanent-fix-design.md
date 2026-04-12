# Design Spec: Permanent nftables Stale-Rules Auto-Heal

**Date:** 2026-04-12  
**Status:** Approved  
**Scope:** `monitoring/guardian-hc/` + `monitoring/guardian-hc/scripts/watchdog.sh`

---

## Background

Docker 29.x on Ubuntu 24.04 (iptables-nft backend) leaves stale DROP rules in
`table ip raw / chain PREROUTING` when bridge networks are destroyed and
recreated. If the new bridge reuses the same subnet, stale rules referencing the
dead bridge ID match all intra-container packets first and silently drop them —
killing all inter-container connectivity.

This bug has hit SOWKNOW4 three times (2026-03-25, 2026-04-10, 2026-04-12),
each time causing full authentication failure and celery outage. Guardian HC was
built to auto-heal it but has two unfixed bugs that have left zero protection:

1. **Detector returns `[]`** — `_find_stale_nftables_bridges()` uses
   `ip link show type bridge` to enumerate live bridges, but dead Docker bridges
   linger in the kernel so the set difference yields nothing.

2. **Healer uses a disruptive 3-step approach** — flush entire raw PREROUTING
   chain → `systemctl restart docker` → force-recreate all containers. ~5
   minutes of downtime. The manual surgical fix (delete only stale handles)
   restores connectivity in under 1 second with zero downtime.

---

## Goals

- Detect and surgically heal stale nftables handles within 2 minutes of onset
- Guardian reports correct stale-bridge data in alerts and dashboard
- No Docker restarts required for healing
- Host watchdog as the primary heal path; Guardian as secondary confirmation

---

## Architecture

Two independent fix paths in one commit:

```
watchdog.sh  (host, root, cron every 2 min)  ← PRIMARY HEAL
  └── check_nftables_stale_rules()
        ├── parse:  nft -a list chain ip raw PREROUTING
        ├── diff:   docker network ls bridge IDs  vs  rule iifname values
        ├── gate:   only heal if stale handles found AND TCP probe fails
        ├── heal:   nft delete rule ip raw PREROUTING handle N  (per handle)
        ├── verify: TCP probe post-heal
        └── alert_healed() / alert()

Guardian network_health.py  ← FIXED DETECTOR
  └── _find_stale_nftables_bridges()
        ├── Docker socket API for live network IDs  (replaces ip link show)
        └── nft -a list chain ip raw PREROUTING  (specific chain + handles)

Guardian network_healer.py  ← REWRITTEN HEALER
  └── heal(stale_bridges)
        ├── nft delete rule ip raw PREROUTING handle N  per stale handle
        ├── TCP probe to verify
        ├── fallback: flush + docker restart if handle deletion fails
        └── no Docker restart in the happy path
```

---

## Watchdog: `check_nftables_stale_rules()`

### Placement
Add as a new function in `scripts/watchdog.sh`, called from the main execution
block alongside the existing five checks (`check_containers`, `check_api`,
`check_worker`, `check_disk`, `check_docker_daemon`).

### Algorithm

```bash
check_nftables_stale_rules() {
  # 1. Get live bridge IDs (first 12 hex chars of Docker network ID)
  live=$(docker network ls --no-trunc --format '{{.ID}}' | cut -c1-12)

  # 2. Parse handles and iifname values from raw PREROUTING
  #    Line format: iifname "br-XXXXXXXXXXXX" ... # handle N
  nft_output=$(nft -a list chain ip raw PREROUTING 2>/dev/null)
  [ -z "$nft_output" ] && return   # nft not available or chain empty

  # 3. Find handles whose iifname bridge is NOT in live_bridges
  #    Build list: "handle:bridge" pairs for stale entries
  stale_handles=()
  while IFS= read -r line; do
    bridge=$(echo "$line" | grep -oP 'iifname "?\K(br-[a-f0-9]{12})(?="?)')
    handle=$(echo "$line" | grep -oP '# handle \K[0-9]+')
    [ -z "$bridge" ] || [ -z "$handle" ] && continue
    echo "$live" | grep -qF "$bridge" && continue   # bridge is live
    stale_handles+=("$handle:$bridge")
  done <<< "$nft_output"

  [ ${#stale_handles[@]} -eq 0 ] && return   # nothing stale

  # 4. TCP probe gate: only heal if connectivity is actually broken
  probe_ok=$(docker exec sowknow4-backend python3 -c \
    "import socket,sys; s=socket.socket(); s.settimeout(3); \
     s.connect(('redis',6379)); print('ok')" 2>/dev/null)
  [ "$probe_ok" = "ok" ] && {
    log "nftables: ${#stale_handles[@]} stale handle(s) found but probes pass — skipping heal"
    return
  }

  # 5. Surgical deletion — one nft call per stale handle
  healed_count=0
  failed_handles=()
  for entry in "${stale_handles[@]}"; do
    handle="${entry%%:*}"
    bridge="${entry##*:}"
    if nft delete rule ip raw PREROUTING handle "$handle" 2>/dev/null; then
      healed_count=$((healed_count + 1))
      log "nftables: deleted stale handle $handle (bridge $bridge)"
    else
      failed_handles+=("$handle")
    fi
  done

  # 6. Verify
  probe_ok=$(docker exec sowknow4-backend python3 -c \
    "import socket,sys; s=socket.socket(); s.settimeout(3); \
     s.connect(('redis',6379)); print('ok')" 2>/dev/null)

  if [ "$probe_ok" = "ok" ]; then
    alert_healed "nftables stale handles deleted: $healed_count handle(s) removed. Connectivity restored."
  else
    alert "nftables heal FAILED after deleting $healed_count handle(s). Probes still failing. Manual intervention required."
  fi
}
```

### Notes
- Requires `nft` on the host (`apt install nftables`) — verified already present.
- Runs as root via cron — no sudo needed.
- No Docker restart, no service disruption.
- The probe gate prevents false-positive heals during clean Docker network teardown.

---

## Guardian: Detector Fix (`network_health.py`)

### Root Cause
`ip link show type bridge` lists kernel bridge interfaces, which persist after
Docker removes a network (kernel GC lag). Using Docker's own network list via
the socket API gives the authoritative set of live bridges.

### Changes to `_find_stale_nftables_bridges()`

Replace the `_host_exec("ip", "link", "show", "type", "bridge")` call with a
Docker socket API call (same httpx+UDS pattern already used by `_tcp_probe`):

```python
async def _find_stale_nftables_bridges(self) -> list[dict]:
    try:
        # 1. Live bridge IDs from Docker API
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://docker", timeout=5) as client:
            resp = await client.get("/networks")
            live_bridges = {
                net["Id"][:12]
                for net in resp.json()
                if net.get("Driver") == "bridge"
            }

        # 2. Parse raw PREROUTING chain on host (with handles)
        rc, nft_out, _ = await _host_exec(
            "nft", "-a", "list", "chain", "ip", "raw", "PREROUTING", timeout=10
        )
        if rc != 0:
            return []

        # 3. Build bridge → [handles] map from iifname lines
        bridge_handles: dict[str, list[int]] = {}
        for line in nft_out.splitlines():
            m_bridge = re.search(r'iifname\s+"?(br-[a-f0-9]{12})"?', line)
            m_handle = re.search(r'#\s+handle\s+(\d+)', line)
            if m_bridge and m_handle:
                br = m_bridge.group(1)
                bridge_handles.setdefault(br, []).append(int(m_handle.group(1)))

        # 4. Stale = in rules but not in live Docker networks
        stale = []
        for br, handles in bridge_handles.items():
            br_id = br.replace("br-", "")
            if br_id not in live_bridges:
                stale.append({
                    "bridge": br,
                    "handles": handles,
                    "rule_count": len(handles),
                })
        return stale

    except Exception as e:
        return [{"bridge": "error", "error": str(e)[:200]}]
```

The returned dicts now include `handles` — used directly by the healer without
re-parsing.

---

## Guardian: Healer Rewrite (`network_healer.py`)

### Changes to `heal()`

Replace the flush+restart 3-step with surgical per-handle deletion:

```python
async def heal(self, stale_bridges: list[dict] = None) -> dict:
    actions = []
    stale = [s for s in (stale_bridges or []) if "handles" in s]

    if not stale:
        return {"healed": False, "error": "no stale handles to delete", "actions": actions}

    # Step 1: Delete stale handles surgically
    deleted, failed = [], []
    for entry in stale:
        for handle in entry["handles"]:
            rc, _, err = await _host_exec(
                "nft", "delete", "rule", "ip", "raw", "PREROUTING",
                "handle", str(handle), timeout=10,
            )
            if rc == 0:
                deleted.append(handle)
            else:
                failed.append((handle, err.strip()[:80]))

    if deleted:
        actions.append(f"deleted stale handles: {deleted}")
    if failed:
        actions.append(f"failed handles: {failed}")

    # Step 2: TCP probe to confirm
    probe_ok = await self._tcp_probe_verify()
    if probe_ok:
        logger.info("network_healer.complete", healed=True, actions=actions)
        return {"healed": True, "actions": actions}

    # Fallback: if surgical delete didn't fix it, flush + docker restart
    if not probe_ok:
        logger.warning("network_healer.fallback_flush")
        rc, _, err = await _host_exec(
            "nft", "flush", "chain", "ip", "raw", "PREROUTING", timeout=10,
        )
        if rc == 0:
            actions.append("fallback: nftables raw PREROUTING flushed")
            rc2, _, _ = await _host_exec(
                "systemctl", "restart", "docker", timeout=60,
            )
            if rc2 == 0:
                actions.append("fallback: Docker daemon restarted")

    return {"healed": len(deleted) > 0, "actions": actions}
```

Add a small helper for the post-heal TCP probe:

```python
async def _tcp_probe_verify(self) -> bool:
    """Quick TCP probe: backend → redis. Returns True if OK."""
    cmd = (
        "python3 -c \""
        "import socket,sys; s=socket.socket(); s.settimeout(3); "
        "s.connect(('redis',6379)); print('ok')\""
    )
    rc, out, _ = await _host_exec("docker", "exec", "sowknow4-backend",
                                   "sh", "-c", cmd, timeout=10)
    return rc == 0 and "ok" in out
```

---

## Error Handling

| Failure | Watchdog response | Guardian response |
|---------|-------------------|-------------------|
| `nft` command not found / fails | `return` silently (nft unavailable) | return `[]` |
| Docker socket unreachable | — | return `[]` (checker degrades gracefully) |
| Handle delete fails | log + try remaining handles; alert if probes still broken | same; fallback flush |
| Probe still broken after heal | `alert()` with message for manual intervention | `healed=False` returned to patrol |
| Dead bridge but probes pass | `return` (no heal — network being torn down cleanly) | report stale bridges but `needs_healing=False` |

---

## Testing Plan

1. **Unit test — detector:** Mock Docker socket `/networks` response + mock `nft -a
   list chain ip raw PREROUTING` output with known stale bridge → assert correct
   handles returned.

2. **Unit test — healer:** Mock `_host_exec` to capture nft delete calls → assert
   called once per handle; mock probe returning True → assert `healed=True`.

3. **Integration smoke (manual):** On VPS, add a dummy DROP rule with a fake bridge
   name, confirm watchdog detects and deletes it within 2 minutes.

---

## Files Changed

| File | Change |
|------|--------|
| `monitoring/guardian-hc/scripts/watchdog.sh` | Add `check_nftables_stale_rules()`, call from main |
| `monitoring/guardian-hc/guardian_hc/checks/network_health.py` | Fix `_find_stale_nftables_bridges()` |
| `monitoring/guardian-hc/guardian_hc/healers/network_healer.py` | Rewrite `heal()`, add `_tcp_probe_verify()` |
| `monitoring/guardian-hc/guardian-hc.sowknow4.yml` | No changes needed |
| `docker-compose.yml` | No changes needed |

No new dependencies. No schema migrations. No container rebuilds required
(Guardian bind-mounts its source at runtime).
