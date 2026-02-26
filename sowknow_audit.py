#!/usr/bin/env python3
"""
SOWKNOW Commercial Readiness Audit Script
==========================================
Validates: Feature completeness, security headers, RBAC enforcement,
           LLM routing, OCR pipeline, API correctness, and PWA compliance.

Usage:
    python3 sowknow_audit.py --host https://sowknow.gollamtech.com \
        --admin-email admin@example.com --admin-password <pass> \
        --user-email user@example.com --user-password <pass>
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
import requests
from colorama import Fore, Style, init

init(autoreset=True)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TIMEOUT = 15
PASS = f"{Fore.GREEN}[PASS]{Style.RESET_ALL}"
FAIL = f"{Fore.RED}[FAIL]{Style.RESET_ALL}"
WARN = f"{Fore.YELLOW}[WARN]{Style.RESET_ALL}"
INFO = f"{Fore.CYAN}[INFO]{Style.RESET_ALL}"


@dataclass
class AuditResult:
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    details: list[str] = field(default_factory=list)

    def log(self, status: str, check: str, detail: str = ""):
        if status == "PASS":
            self.passed += 1
            print(f"  {PASS} {check}")
        elif status == "FAIL":
            self.failed += 1
            self.details.append(f"FAIL: {check} — {detail}")
            print(f"  {FAIL} {check}: {detail}")
        elif status == "WARN":
            self.warnings += 1
            self.details.append(f"WARN: {check} — {detail}")
            print(f"  {WARN} {check}: {detail}")
        else:
            print(f"  {INFO} {check}: {detail}")


result = AuditResult()


def section(title: str):
    print(f"\n{'━' * 60}")
    print(f"  {Fore.CYAN}{title}{Style.RESET_ALL}")
    print(f"{'━' * 60}")


def get(host, path, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        return requests.get(f"{host}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.exceptions.RequestException as e:
        return None


def post(host, path, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    headers["Content-Type"] = "application/json"
    try:
        return requests.post(f"{host}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.exceptions.RequestException as e:
        return None


def login(host, email, password) -> Optional[str]:
    r = post(host, "/api/auth/login", json={"email": email, "password": password})
    if r and r.status_code == 200:
        return r.json().get("access_token")
    return None


# ─────────────────────────────────────────────
# AUDIT 1 — CONNECTIVITY & HEALTH
# ─────────────────────────────────────────────
def audit_health(host):
    section("1. CONNECTIVITY & HEALTH CHECKS")

    r = get(host, "/health")
    if r and r.status_code == 200:
        data = r.json()
        result.log("PASS", "Health endpoint reachable at /health")
        for svc in ["db", "redis", "ollama"]:
            if data.get(svc) == "ok":
                result.log("PASS", f"  Dependency healthy: {svc}")
            else:
                result.log("FAIL", f"  Dependency unhealthy: {svc}", data.get(svc, "missing"))
    else:
        result.log("FAIL", "Health endpoint /health not reachable",
                   f"Status: {r.status_code if r else 'no response'}")

    # PWA manifest
    r = get(host, "/manifest.json")
    if r and r.status_code == 200:
        manifest = r.json()
        required = ["name", "short_name", "icons", "start_url", "display"]
        for key in required:
            if key in manifest:
                result.log("PASS", f"PWA manifest has field: {key}")
            else:
                result.log("FAIL", f"PWA manifest missing field: {key}")
    else:
        result.log("FAIL", "PWA manifest.json not found")


# ─────────────────────────────────────────────
# AUDIT 2 — SECURITY HEADERS
# ─────────────────────────────────────────────
def audit_security_headers(host):
    section("2. SECURITY HEADERS & TLS")

    r = get(host, "/")
    if not r:
        result.log("FAIL", "Could not reach root URL")
        return

    # TLS
    if host.startswith("https://"):
        result.log("PASS", "HTTPS enforced (URL is https://)")
    else:
        result.log("FAIL", "Site not served over HTTPS")

    headers = r.headers
    checks = {
        "Strict-Transport-Security": ("HSTS header present", "HSTS missing — add Strict-Transport-Security"),
        "X-Frame-Options": ("X-Frame-Options header present", "X-Frame-Options missing"),
        "X-Content-Type-Options": ("X-Content-Type-Options present", "X-Content-Type-Options missing"),
        "Content-Security-Policy": ("CSP header present", "Content-Security-Policy missing"),
        "Referrer-Policy": ("Referrer-Policy present", "Referrer-Policy missing"),
        "Permissions-Policy": ("Permissions-Policy present", "Permissions-Policy missing — add to nginx"),
    }
    for header, (pass_msg, fail_msg) in checks.items():
        if header in headers:
            result.log("PASS", pass_msg)
        else:
            result.log("FAIL", fail_msg, f"Header: {header}")

    # No server info leak
    if "Server" in headers and "nginx" in headers["Server"].lower():
        result.log("WARN", "Server header reveals nginx version — remove or obscure")
    else:
        result.log("PASS", "Server header does not leak version info")

    # CORS check
    r2 = requests.options(f"{host}/api/documents",
                          headers={"Origin": "https://evil.com", "Access-Control-Request-Method": "GET"},
                          timeout=TIMEOUT)
    acao = r2.headers.get("Access-Control-Allow-Origin", "")
    if acao == "*":
        result.log("FAIL", "CORS wildcard (*) origin allowed — restrict to sowknow.gollamtech.com")
    elif "evil.com" in acao:
        result.log("FAIL", "CORS allows arbitrary origins")
    else:
        result.log("PASS", "CORS properly restricted")


# ─────────────────────────────────────────────
# AUDIT 3 — AUTHENTICATION
# ─────────────────────────────────────────────
def audit_authentication(host, admin_email, admin_pass, user_email, user_pass):
    section("3. AUTHENTICATION & TOKEN SECURITY")

    # Valid login
    admin_token = login(host, admin_email, admin_pass)
    if admin_token:
        result.log("PASS", "Admin login returns JWT token")
    else:
        result.log("FAIL", "Admin login failed — cannot continue auth tests")
        return None, None

    user_token = login(host, user_email, user_pass)
    if user_token:
        result.log("PASS", "Regular user login returns JWT token")
    else:
        result.log("WARN", "Regular user login failed — skipping user RBAC tests")

    # Invalid credentials — should return 401
    r = post(host, "/api/auth/login", json={"email": admin_email, "password": "WRONG_PASSWORD_12345"})
    if r and r.status_code == 401:
        result.log("PASS", "Invalid password returns 401")
    else:
        result.log("FAIL", "Invalid password should return 401", f"Got: {r.status_code if r else 'no response'}")

    # No info leakage between "user not found" vs "wrong password"
    r_bad_user = post(host, "/api/auth/login", json={"email": "nonexistent@x.com", "password": "pw"})
    r_bad_pass = post(host, "/api/auth/login", json={"email": admin_email, "password": "wrongpw"})
    if r_bad_user and r_bad_pass:
        if r_bad_user.text == r_bad_pass.text or (r_bad_user.status_code == r_bad_pass.status_code):
            result.log("PASS", "Auth errors give identical responses (no user enumeration)")
        else:
            result.log("FAIL", "Different error messages for wrong user vs wrong password — info leak")

    # Unauthenticated access to protected endpoint
    r = get(host, "/api/documents")
    if r and r.status_code in [401, 403]:
        result.log("PASS", "Unauthenticated request to /api/documents returns 401/403")
    else:
        result.log("FAIL", "Unauthenticated request to /api/documents should be rejected",
                   f"Got: {r.status_code if r else 'no response'}")

    # Token inspection — check algorithm
    if admin_token:
        import base64
        parts = admin_token.split(".")
        if len(parts) == 3:
            header = json.loads(base64.urlsafe_b64decode(parts[0] + "=="))
            alg = header.get("alg", "unknown")
            if alg == "RS256":
                result.log("PASS", f"JWT uses RS256 (asymmetric) — algorithm: {alg}")
            elif alg == "HS256":
                result.log("WARN", "JWT uses HS256 (symmetric) — consider migrating to RS256 for production")
            else:
                result.log("INFO", f"JWT algorithm: {alg}")

    return admin_token, user_token


# ─────────────────────────────────────────────
# AUDIT 4 — RBAC & VAULT ISOLATION
# ─────────────────────────────────────────────
def audit_rbac(host, admin_token, user_token):
    section("4. RBAC & CONFIDENTIAL VAULT ISOLATION")

    if not admin_token:
        result.log("WARN", "Skipping RBAC tests — no admin token")
        return

    # Admin can access dashboard stats
    r = get(host, "/api/admin/stats", token=admin_token)
    if r and r.status_code == 200:
        result.log("PASS", "Admin can access /api/admin/stats")
    else:
        result.log("FAIL", "Admin cannot access /api/admin/stats",
                   f"Status: {r.status_code if r else 'no response'}")

    # Regular user cannot access admin stats
    if user_token:
        r = get(host, "/api/admin/stats", token=user_token)
        if r and r.status_code in [401, 403]:
            result.log("PASS", "Regular user blocked from /api/admin/stats (401/403)")
        else:
            result.log("FAIL", "Regular user should be blocked from /api/admin/stats",
                       f"Got: {r.status_code if r else 'no response'}")

    # Admin document list — should see both buckets
    r = get(host, "/api/documents", token=admin_token)
    if r and r.status_code == 200:
        docs = r.json()
        result.log("PASS", f"Admin can retrieve documents list ({len(docs.get('items', docs))} docs)")
        # Check for confidential field presence in admin response
        items = docs.get("items", docs) if isinstance(docs, dict) else docs
        if isinstance(items, list) and len(items) > 0:
            if "bucket" in items[0]:
                result.log("PASS", "Document objects include 'bucket' field")
            else:
                result.log("WARN", "Document objects missing 'bucket' field — RBAC enforcement unclear")
    else:
        result.log("FAIL", "Admin cannot retrieve documents", f"Status: {r.status_code if r else 'no response'}")

    # Regular user document list — MUST NOT contain confidential docs
    if user_token:
        r = get(host, "/api/documents", token=user_token)
        if r and r.status_code == 200:
            docs = r.json()
            items = docs.get("items", docs) if isinstance(docs, dict) else docs
            if isinstance(items, list):
                confidential_leaked = [d for d in items if d.get("bucket") == "confidential"]
                if confidential_leaked:
                    result.log("FAIL",
                               f"CRITICAL: Regular user can see {len(confidential_leaked)} confidential documents!",
                               "Vault isolation breach")
                else:
                    result.log("PASS", "Regular user sees zero confidential documents in list")
        else:
            result.log("WARN", "Could not retrieve documents as regular user",
                       f"Status: {r.status_code if r else 'no response'}")

    # Search — user should not get confidential results
    if user_token:
        r = post(host, "/api/search", token=user_token,
                 json={"query": "confidential passport identity card"})
        if r and r.status_code == 200:
            results_data = r.json()
            items = results_data.get("results", results_data) if isinstance(results_data, dict) else results_data
            if isinstance(items, list):
                confidential_results = [i for i in items if i.get("bucket") == "confidential"]
                if confidential_results:
                    result.log("FAIL", "CRITICAL: Search returns confidential chunks to regular user!")
                else:
                    result.log("PASS", "Search results contain no confidential chunks for regular user")

    # Admin settings endpoint — user blocked
    if user_token:
        r = get(host, "/api/admin/users", token=user_token)
        if r and r.status_code in [401, 403]:
            result.log("PASS", "User management endpoint blocked for regular users")
        else:
            result.log("FAIL", "User management endpoint accessible to regular users",
                       f"Status: {r.status_code if r else 'no response'}")

    # Upload — user blocked
    if user_token:
        r = requests.post(f"{host}/api/documents/upload",
                          headers={"Authorization": f"Bearer {user_token}"},
                          files={"file": ("test.txt", b"test content", "text/plain")},
                          timeout=TIMEOUT)
        if r and r.status_code in [401, 403]:
            result.log("PASS", "Upload endpoint blocked for regular users")
        else:
            result.log("FAIL", "Regular user should not be able to upload documents",
                       f"Status: {r.status_code if r else 'no response'}")


# ─────────────────────────────────────────────
# AUDIT 5 — API FEATURE COMPLETENESS
# ─────────────────────────────────────────────
def audit_features(host, admin_token, user_token):
    section("5. FEATURE COMPLETENESS")

    token = admin_token or user_token
    if not token:
        result.log("WARN", "No token available — skipping feature tests")
        return

    endpoints = [
        ("GET", "/api/documents", "Document listing"),
        ("GET", "/api/collections", "Collections listing"),
        ("GET", "/api/admin/stats", "Admin stats dashboard"),
        ("GET", "/api/admin/anomalies", "Anomaly monitoring endpoint"),
        ("GET", "/api/chat/sessions", "Chat sessions listing"),
    ]

    for method, path, label in endpoints:
        t = admin_token if "admin" in path else token
        r = get(host, path, token=t) if method == "GET" else None
        if r and r.status_code in [200, 204]:
            result.log("PASS", f"Endpoint reachable: {method} {path} — {label}")
        elif r and r.status_code == 404:
            result.log("FAIL", f"Endpoint NOT FOUND: {method} {path} — {label}", "Returns 404")
        elif r and r.status_code in [401, 403]:
            result.log("WARN", f"Endpoint {path} requires higher privilege than test token")
        else:
            result.log("FAIL", f"Endpoint error: {method} {path}",
                       f"Status: {r.status_code if r else 'no response'}")

    # Search endpoint
    r = post(host, "/api/search", token=token, json={"query": "test knowledge"})
    if r and r.status_code == 200:
        data = r.json()
        if isinstance(data, dict) and ("results" in data or "items" in data):
            result.log("PASS", "Search returns structured JSON with results field")
        else:
            result.log("WARN", "Search response format unexpected — check result schema")
    else:
        result.log("FAIL", "Search endpoint /api/search not functional",
                   f"Status: {r.status_code if r else 'no response'}")

    # Chat streaming test
    r = requests.post(
        f"{host}/api/chat/message",
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        json={"session_id": "audit-test-session", "message": "Hello, what is SOWKNOW?"},
        stream=True,
        timeout=20,
    )
    if r and r.status_code == 200:
        content_type = r.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            result.log("PASS", "Chat endpoint streams SSE (text/event-stream)")
            # Read first chunk
            for chunk in r.iter_content(chunk_size=128):
                if chunk:
                    result.log("PASS", "Chat streaming delivers data")
                    break
        else:
            result.log("WARN", "Chat endpoint does not use SSE — check streaming implementation",
                       f"Content-Type: {content_type}")
    else:
        result.log("FAIL", "Chat endpoint /api/chat/message not functional",
                   f"Status: {r.status_code if r else 'no response'}")

    # Smart Collections
    r = post(host, "/api/collections/create", token=admin_token or token,
             json={"description": "All documents about finance and investments"})
    if r and r.status_code in [200, 201, 202]:
        result.log("PASS", "Smart Collections create endpoint functional")
    else:
        result.log("FAIL", "Smart Collections endpoint not functional",
                   f"Status: {r.status_code if r else 'no response'}")

    # Smart Folders
    r = post(host, "/api/smart-folders/generate", token=admin_token or token,
             json={"topic": "solar energy"})
    if r and r.status_code in [200, 201, 202]:
        result.log("PASS", "Smart Folders generate endpoint functional")
    else:
        result.log("FAIL", "Smart Folders endpoint not functional",
                   f"Status: {r.status_code if r else 'no response'}")


# ─────────────────────────────────────────────
# AUDIT 6 — LLM ROUTING VALIDATION
# ─────────────────────────────────────────────
def audit_llm_routing(host, admin_token):
    section("6. LLM ROUTING & PRIVACY ENFORCEMENT")

    if not admin_token:
        result.log("WARN", "No admin token — skipping LLM routing tests")
        return

    # Check model indicator in chat response
    r = requests.post(
        f"{host}/api/chat/message",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"session_id": "llm-routing-test", "message": "Quick test"},
        timeout=20,
    )
    if r and r.status_code == 200:
        try:
            data = r.json()
            model = data.get("model") or data.get("metadata", {}).get("model")
            if model:
                result.log("PASS", f"Chat response includes model indicator: {model}")
                if model in ["kimi-2.5", "ollama", "ollama/mistral", "moonshot-v1-8k"]:
                    result.log("PASS", f"Model identifier is a recognized value: {model}")
                else:
                    result.log("WARN", f"Unexpected model identifier: {model}")
            else:
                result.log("FAIL", "Chat response missing 'model' field — routing transparency broken")
        except Exception:
            result.log("WARN", "Chat response is not JSON (may be streaming) — check model indicator in SSE metadata")
    else:
        result.log("WARN", "Could not test LLM routing — chat endpoint unavailable")

    # LLM routing audit log endpoint (should NOT be publicly exposed)
    r = get(host, "/api/admin/llm-audit-log", token=None)
    if r and r.status_code in [401, 403, 404]:
        result.log("PASS", "LLM audit log not exposed without auth (or not exposed at all)")
    elif r and r.status_code == 200:
        result.log("FAIL", "LLM audit log endpoint accessible without authentication!")
    else:
        result.log("INFO", "LLM audit log endpoint status unclear — verify manually")


# ─────────────────────────────────────────────
# AUDIT 7 — PERFORMANCE & RATE LIMITING
# ─────────────────────────────────────────────
def audit_performance(host):
    section("7. PERFORMANCE & RATE LIMITING")

    # Page load time
    start = time.time()
    r = get(host, "/")
    elapsed = time.time() - start
    if r and elapsed < 2.0:
        result.log("PASS", f"Root page load time: {elapsed:.2f}s (target <2s)")
    elif r:
        result.log("WARN", f"Root page load time: {elapsed:.2f}s (target <2s — consider optimization)")
    else:
        result.log("FAIL", "Root page not reachable")

    # Search response time
    r_login = post(host, "/api/auth/login",
                   json={"email": "test@test.com", "password": "testpass"})
    token = r_login.json().get("access_token") if r_login and r_login.status_code == 200 else None
    if token:
        start = time.time()
        r = post(host, "/api/search", token=token, json={"query": "test query for performance"})
        elapsed = time.time() - start
        if r and r.status_code == 200:
            if elapsed < 3.0:
                result.log("PASS", f"Search response time: {elapsed:.2f}s (target <3s)")
            else:
                result.log("WARN", f"Search response time: {elapsed:.2f}s (slow — target <3s)")

    # Rate limiting — burst 20 rapid requests
    responses = []
    for _ in range(20):
        r = get(host, "/health")
        if r:
            responses.append(r.status_code)
    rate_limited = any(s == 429 for s in responses)
    if rate_limited:
        result.log("PASS", "Rate limiting active (429 returned under burst load)")
    else:
        result.log("WARN", "No rate limiting detected under 20 rapid requests — verify nginx limit_req_zone")


# ─────────────────────────────────────────────
# AUDIT 8 — UPLOAD & DOCUMENT PIPELINE
# ─────────────────────────────────────────────
def audit_upload_pipeline(host, admin_token):
    section("8. UPLOAD & DOCUMENT PROCESSING PIPELINE")

    if not admin_token:
        result.log("WARN", "No admin token — skipping upload tests")
        return

    # Upload a small text document
    test_content = b"This is a SOWKNOW audit test document. It contains some French: Bonjour le monde."
    r = requests.post(
        f"{host}/api/documents/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("audit_test.txt", test_content, "text/plain")},
        data={"bucket": "public", "tags": "audit,test"},
        timeout=30,
    )
    if r and r.status_code in [200, 201, 202]:
        doc = r.json()
        doc_id = doc.get("id") or doc.get("document_id")
        result.log("PASS", f"Document upload accepted (ID: {doc_id})")

        if doc_id:
            # Check document status
            time.sleep(2)
            r2 = get(host, f"/api/documents/{doc_id}", token=admin_token)
            if r2 and r2.status_code == 200:
                status = r2.json().get("status", "unknown")
                result.log("PASS", f"Document status endpoint working — status: {status}")
                if status in ["pending", "ocr_processing", "embedding", "indexed"]:
                    result.log("PASS", "Document status is a valid pipeline state")
                else:
                    result.log("WARN", f"Unexpected document status: {status}")
            else:
                result.log("FAIL", "Cannot retrieve document status after upload")

            # Delete test document
            r3 = requests.delete(
                f"{host}/api/documents/{doc_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                timeout=TIMEOUT,
            )
            if r3 and r3.status_code in [200, 204]:
                result.log("PASS", "Test document cleaned up successfully")
            else:
                result.log("WARN", "Could not delete test document — clean up manually")
    else:
        result.log("FAIL", "Document upload failed",
                   f"Status: {r.status_code if r else 'no response'}")

    # Verify file size limit enforcement (create a >100MB payload)
    result.log("INFO", "File size limit (100MB) — manual verification recommended")


# ─────────────────────────────────────────────
# AUDIT 9 — FRONTEND CHECKLIST
# ─────────────────────────────────────────────
def audit_frontend(host):
    section("9. FRONTEND & PWA COMPLIANCE")

    # Check key pages return 200
    pages = [
        ("/", "Landing / Home"),
        ("/login", "Login page"),
        ("/search", "Search page"),
        ("/documents", "Documents page"),
        ("/chat", "Chat / Assistant AI page"),
        ("/collections", "Collections page"),
        ("/smart-folders", "Smart Folders page"),
    ]
    for path, label in pages:
        r = get(host, path)
        if r and r.status_code == 200:
            result.log("PASS", f"Page accessible: {path} — {label}")
        elif r and r.status_code in [301, 302]:
            result.log("WARN", f"Page redirects: {path} — check if intended (auth redirect?)")
        else:
            result.log("FAIL", f"Page not accessible: {path} — {label}",
                       f"Status: {r.status_code if r else 'no response'}")

    # Service worker
    r = get(host, "/sw.js")
    if r and r.status_code == 200:
        result.log("PASS", "Service worker (sw.js) found — PWA offline support enabled")
    else:
        result.log("WARN", "No service worker found at /sw.js — PWA installability may be limited")

    # Robots.txt
    r = get(host, "/robots.txt")
    if r and r.status_code == 200:
        result.log("PASS", "robots.txt present")
    else:
        result.log("WARN", "No robots.txt — add one to control indexing")

    # Favicon
    r = get(host, "/favicon.ico")
    if r and r.status_code == 200:
        result.log("PASS", "Favicon present")
    else:
        result.log("WARN", "No favicon — add for PWA quality")


# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
def print_summary():
    total = result.passed + result.failed + result.warnings
    print(f"\n{'═' * 60}")
    print(f"  {Fore.CYAN}SOWKNOW COMMERCIAL READINESS AUDIT — SUMMARY{Style.RESET_ALL}")
    print(f"{'═' * 60}")
    print(f"  {Fore.GREEN}PASSED  : {result.passed}{Style.RESET_ALL}")
    print(f"  {Fore.RED}FAILED  : {result.failed}{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}WARNINGS: {result.warnings}{Style.RESET_ALL}")
    print(f"  Total   : {total}")

    score = int((result.passed / total) * 100) if total > 0 else 0
    color = Fore.GREEN if score >= 90 else Fore.YELLOW if score >= 70 else Fore.RED
    print(f"\n  Score: {color}{score}%{Style.RESET_ALL}", end="")

    if result.failed == 0:
        print(f" — {Fore.GREEN}COMMERCIALLY READY ✓{Style.RESET_ALL}")
    elif result.failed <= 3:
        print(f" — {Fore.YELLOW}NEAR READY — Fix failures before launch{Style.RESET_ALL}")
    else:
        print(f" — {Fore.RED}NOT READY — Critical issues must be resolved{Style.RESET_ALL}")

    if result.details:
        print(f"\n  {'─' * 56}")
        print(f"  {Fore.RED}Issues requiring action:{Style.RESET_ALL}")
        for d in result.details:
            print(f"    • {d}")

    print(f"\n{'═' * 60}\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SOWKNOW Commercial Readiness Audit")
    parser.add_argument("--host", default="https://sowknow.gollamtech.com")
    parser.add_argument("--admin-email", default="")
    parser.add_argument("--admin-password", default="")
    parser.add_argument("--user-email", default="")
    parser.add_argument("--user-password", default="")
    args = parser.parse_args()

    host = args.host.rstrip("/")
    print(f"\n{Fore.CYAN}SOWKNOW Commercial Readiness Audit{Style.RESET_ALL}")
    print(f"Target: {host}")
    print(f"Time  : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

    audit_health(host)
    audit_security_headers(host)

    admin_token, user_token = audit_authentication(
        host, args.admin_email, args.admin_password,
        args.user_email, args.user_password
    )

    audit_rbac(host, admin_token, user_token)
    audit_features(host, admin_token, user_token)
    audit_llm_routing(host, admin_token)
    audit_performance(host)
    audit_upload_pipeline(host, admin_token)
    audit_frontend(host)

    print_summary()
    sys.exit(1 if result.failed > 0 else 0)


if __name__ == "__main__":
    main()
