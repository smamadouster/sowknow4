# Credential Rotation Log

Track all credential rotations and security remediations here.
Each entry must include: date, credential type, reason, and operator.

---

## 2026-02-26 — Initial remediation (LLM integration security audit)

| Credential | Action | Reason | Operator |
|---|---|---|---|
| `MOONSHOT_API_KEY` (sk-kimi-…) | Rotated | Key exposed in git history via .env.example commit | System |
| `JWT_SECRET` | Placeholder updated | Replaced with generation instruction in .env.example | System |
| `ADMIN_PASSWORD` | Placeholder updated | Replaced with strong placeholder | System |

**Actions taken:**
- `.env.example` updated: all real-looking values replaced with `YOUR_*_HERE` placeholders
- `OPENROUTER_API_KEY` and `MINIMAX_API_KEY` placeholders added
- `LOCAL_LLM_URL` renamed to canonical `OLLAMA_BASE_URL` across all config files
- `scripts/setup_env.sh` created to auto-generate secrets on first setup

**Remediation status:** ✅ All .env.example values are now safe placeholders.

---

## Rotation Schedule

| Credential | Rotation Frequency | Last Rotated | Next Due |
|---|---|---|---|
| `MOONSHOT_API_KEY` | 90 days | 2026-02-26 | 2026-05-27 |
| `OPENROUTER_API_KEY` | 90 days | 2026-02-26 | 2026-05-27 |
| `MINIMAX_API_KEY` | 90 days | 2026-02-26 | 2026-05-27 |
| `JWT_SECRET` | 180 days | 2026-02-26 | 2026-08-25 |
| `DATABASE_PASSWORD` | 90 days | 2026-02-26 | 2026-05-27 |
| `REDIS_PASSWORD` | 90 days | 2026-02-26 | 2026-05-27 |
| `BOT_API_KEY` | 90 days | 2026-02-26 | 2026-05-27 |

---

## How to Rotate a Credential

1. Generate a new value (use `openssl rand -hex 32` for secrets)
2. Update the value in the production `.env` on the VPS
3. Restart the affected container(s): `docker compose restart <service>`
4. Verify the service is healthy: `docker compose ps`
5. Update this log with the rotation date and operator
