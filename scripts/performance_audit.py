#!/usr/bin/env python3
"""
Performance Audit Script for SOWKNOW
=====================================

Benchmarks the SOWKNOW API against PRD targets:
- Search latency: <3s (Gemini), <8s (Ollama)
- First chat token: <2s (Gemini), <5s (Ollama)
- Page load: <2s
- Upload throughput: >50 docs/hour
- Concurrent users: 5 simultaneous without degradation

Usage:
    python scripts/performance_audit.py --env local
    python scripts/performance_audit.py --env production
    python scripts/performance_audit.py --base-url http://localhost:8000
"""

import argparse
import asyncio
import getpass
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install with: pip install httpx")
    sys.exit(1)


# PRD Targets
TARGETS = {
    "search_latency_p50": 3.0,      # seconds
    "search_latency_p95": 5.0,      # seconds
    "chat_first_token_gemini": 2.0, # seconds
    "chat_first_token_ollama": 5.0, # seconds
    "page_load": 2.0,               # seconds
    "upload_throughput": 50,        # docs/hour
    "concurrent_users": 5,
}

# Environment configurations
ENVIRONMENTS = {
    "local": "http://localhost:8000",
    "production": "https://sowknow.gollamtech.com",
}

# Test queries for benchmarking
TEST_SEARCH_QUERIES = [
    "solar energy",
    "investment portfolio",
    "family vacation photos",
    "tax documents 2024",
    "meeting notes project alpha",
    "medical records",
    "insurance policy",
    "home renovation",
    "vehicle maintenance",
    "education certificates",
]

# Test pages to benchmark
TEST_PAGES = [
    "/",                    # Landing
    "/dashboard",           # Main dashboard
    "/documents",           # Document list
    "/search",              # Search page
    "/chat",                # Chat interface
]


@dataclass
class BenchmarkResult:
    """Single benchmark measurement"""
    name: str
    value: float
    unit: str
    target: float
    passed: bool
    details: dict = field(default_factory=dict)


@dataclass
class AuditReport:
    """Complete audit report"""
    timestamp: str
    environment: str
    base_url: str
    results: list = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return self.passed / len(self.results) * 100

    def add_result(self, result: BenchmarkResult):
        self.results.append(result)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "environment": self.environment,
            "base_url": self.base_url,
            "summary": {
                "total": len(self.results),
                "passed": self.passed,
                "failed": self.failed,
                "pass_rate": f"{self.pass_rate:.1f}%",
            },
            "results": [
                {
                    "name": r.name,
                    "value": f"{r.value:.3f}" if r.value else "N/A",
                    "unit": r.unit,
                    "target": f"{r.target:.3f}" if r.target else "N/A",
                    "passed": "✓ PASS" if r.passed else "✗ FAIL",
                    "details": r.details,
                }
                for r in self.results
            ],
        }

    def print_summary(self):
        """Print formatted summary to console"""
        print("\n" + "=" * 70)
        print("SOWKNOW PERFORMANCE AUDIT REPORT")
        print("=" * 70)
        print(f"Timestamp:   {self.timestamp}")
        print(f"Environment: {self.environment}")
        print(f"Base URL:    {self.base_url}")
        print("-" * 70)
        print(f"{'Benchmark':<35} {'Value':>12} {'Target':>12} {'Status':>10}")
        print("-" * 70)

        for r in self.results:
            value_str = f"{r.value:.3f} {r.unit}" if r.value else "N/A"
            target_str = f"{r.target:.3f} {r.unit}" if r.target else "N/A"
            status = "✓ PASS" if r.passed else "✗ FAIL"
            print(f"{r.name:<35} {value_str:>12} {target_str:>12} {status:>10}")

        print("-" * 70)
        print(f"SUMMARY: {self.passed}/{len(self.results)} passed ({self.pass_rate:.1f}%)")
        print("=" * 70)


class SOWKNOWClient:
    """Authenticated client for SOWKNOW API"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"
        self.client: Optional[httpx.AsyncClient] = None
        self.cookies: dict = {}
        self.user_info: Optional[dict] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()

    async def login(self, email: str, password: str) -> bool:
        """
        Authenticate and store session cookies.

        The API uses httpOnly cookies for authentication.
        """
        try:
            response = await self.client.post(
                f"{self.api_base}/auth/login",
                data={  # Form-encoded, not JSON
                    "username": email,
                    "password": password,
                },
            )

            if response.status_code == 200:
                # Extract cookies from response
                self.cookies = dict(response.cookies)
                self.user_info = response.json().get("user", {})
                print(f"✓ Logged in as: {self.user_info.get('email', email)} "
                      f"(role: {self.user_info.get('role', 'unknown')})")
                return True
            else:
                print(f"✗ Login failed: {response.status_code}")
                print(f"  Response: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"✗ Login error: {e}")
            return False

    async def refresh_token(self) -> bool:
        """Refresh the access token"""
        try:
            response = await self.client.post(
                f"{self.api_base}/auth/refresh",
                cookies=self.cookies,
            )
            if response.status_code == 200:
                self.cookies = dict(response.cookies)
                return True
            return False
        except Exception:
            return False

    async def logout(self):
        """End the session"""
        try:
            await self.client.post(
                f"{self.api_base}/auth/logout",
                cookies=self.cookies,
            )
        except Exception:
            pass

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make authenticated request"""
        kwargs.setdefault("cookies", self.cookies)
        return await self.client.request(method, f"{self.api_base}{path}", **kwargs)

    # Search API
    async def search(self, query: str, limit: int = 20) -> httpx.Response:
        """Perform semantic search"""
        return await self._request(
            "POST",
            "/search",
            json={"query": query, "limit": limit},
        )

    # Chat API
    async def create_chat_session(self, title: str = "Performance Test Session") -> httpx.Response:
        """Create a new chat session"""
        return await self._request(
            "POST",
            "/chat/sessions",
            json={"title": title},
        )

    async def send_chat_message(self, session_id: str, message: str, stream: bool = True) -> httpx.Response:
        """Send a chat message"""
        return await self._request(
            "POST",
            f"/chat/sessions/{session_id}/message",  # Note: singular "message"
            json={"content": message},
            params={"stream": stream},
        )

    async def stream_chat_message(self, session_id: str, message: str):
        """Stream chat response, yield first token latency"""
        start = time.monotonic()
        first_token_time = None

        async with self.client.stream(
            "POST",
            f"{self.api_base}/chat/sessions/{session_id}/message",  # Note: singular "message"
            json={"content": message},
            params={"stream": True},
            cookies=self.cookies,
        ) as response:
            async for chunk in response.aiter_bytes():
                if first_token_time is None:
                    first_token_time = time.monotonic() - start
                    yield first_token_time
                # Continue consuming the stream
                pass

        if first_token_time is None:
            yield time.monotonic() - start

    # Document API
    async def upload_document(self, file_path: str) -> httpx.Response:
        """Upload a document"""
        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f, "application/pdf")}
            return await self._request("POST", "/documents/upload", files=files)

    async def list_documents(self, limit: int = 20) -> httpx.Response:
        """List documents"""
        return await self._request("GET", f"/documents?limit={limit}")

    # Page loading (frontend)
    async def load_page(self, path: str) -> httpx.Response:
        """Load a frontend page"""
        return await self.client.get(f"{self.base_url}{path}")


class PerformanceAuditor:
    """Run performance benchmarks against SOWKNOW"""

    def __init__(self, client: SOWKNOWClient, report: AuditReport):
        self.client = client
        self.report = report

    async def benchmark_search(self, queries: list[str], n: int = 20) -> BenchmarkResult:
        """
        Benchmark search latency.
        PRD Target: <3s for semantic search queries
        """
        print(f"\n🔍 Benchmarking search latency ({min(n, len(queries))} queries)...")

        latencies = []
        errors = []

        for query in queries[:n]:
            start = time.monotonic()
            try:
                response = await self.client.search(query)
                elapsed = time.monotonic() - start

                if response.status_code == 200:
                    latencies.append(elapsed)
                    print(f"  '{query[:30]}...': {elapsed:.3f}s")
                else:
                    errors.append(f"Query '{query}': HTTP {response.status_code}")

            except Exception as e:
                errors.append(f"Query '{query}': {e}")

            # Small delay between requests
            await asyncio.sleep(0.1)

        if not latencies:
            return BenchmarkResult(
                name="Search Latency",
                value=0,
                unit="s",
                target=TARGETS["search_latency_p50"],
                passed=False,
                details={"error": "No successful searches", "errors": errors},
            )

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(0.95 * len(latencies))] if len(latencies) > 1 else latencies[0]
        p99 = sorted(latencies)[int(0.99 * len(latencies))] if len(latencies) > 1 else latencies[0]

        result = BenchmarkResult(
            name="Search Latency (p50)",
            value=p50,
            unit="s",
            target=TARGETS["search_latency_p50"],
            passed=p50 < TARGETS["search_latency_p50"],
            details={
                "p50": f"{p50:.3f}s",
                "p95": f"{p95:.3f}s",
                "p99": f"{p99:.3f}s",
                "max": f"{max(latencies):.3f}s",
                "min": f"{min(latencies):.3f}s",
                "samples": len(latencies),
                "errors": errors[:5] if errors else [],
            },
        )
        self.report.add_result(result)

        # Also add p95 result
        self.report.add_result(BenchmarkResult(
            name="Search Latency (p95)",
            value=p95,
            unit="s",
            target=TARGETS["search_latency_p95"],
            passed=p95 < TARGETS["search_latency_p95"],
            details={"samples": len(latencies)},
        ))

        return result

    async def benchmark_chat_first_token(self, n: int = 10) -> BenchmarkResult:
        """
        Benchmark first chat token latency.
        PRD Target: <2s (Gemini), <5s (Ollama)
        """
        print(f"\n💬 Benchmarking chat first token latency ({n} messages)...")

        # Create a chat session first
        session_response = await self.client.create_chat_session()
        if session_response.status_code != 200:
            return BenchmarkResult(
                name="Chat First Token",
                value=0,
                unit="s",
                target=TARGETS["chat_first_token_gemini"],
                passed=False,
                details={"error": f"Failed to create chat session: {session_response.status_code}"},
            )

        session_id = session_response.json().get("id")
        if not session_id:
            return BenchmarkResult(
                name="Chat First Token",
                value=0,
                unit="s",
                target=TARGETS["chat_first_token_gemini"],
                passed=False,
                details={"error": "No session ID in response"},
            )

        print(f"  Created chat session: {session_id[:8]}...")

        latencies = []
        test_messages = [
            "What documents do I have about solar energy?",
            "Summarize my investment portfolio",
            "Find information about my family",
            "What are my upcoming tasks?",
            "Tell me about my education history",
        ]

        for i, message in enumerate(test_messages[:n]):
            try:
                print(f"  Message {i+1}/{n}: '{message[:40]}...'")
                async for first_token_time in self.client.stream_chat_message(session_id, message):
                    latencies.append(first_token_time)
                    print(f"    First token: {first_token_time:.3f}s")
                    break

            except Exception as e:
                print(f"    Error: {e}")

            await asyncio.sleep(0.5)  # Delay between messages

        if not latencies:
            return BenchmarkResult(
                name="Chat First Token",
                value=0,
                unit="s",
                target=TARGETS["chat_first_token_gemini"],
                passed=False,
                details={"error": "No successful chat responses"},
            )

        p50 = statistics.median(latencies)

        result = BenchmarkResult(
            name="Chat First Token (p50)",
            value=p50,
            unit="s",
            target=TARGETS["chat_first_token_gemini"],
            passed=p50 < TARGETS["chat_first_token_gemini"],
            details={
                "p50": f"{p50:.3f}s",
                "p95": f"{sorted(latencies)[int(0.95 * len(latencies))]:.3f}s" if len(latencies) > 1 else f"{latencies[0]:.3f}s",
                "samples": len(latencies),
                "note": "Target is for Gemini Flash; Ollama allows <5s",
            },
        )
        self.report.add_result(result)
        return result

    async def benchmark_page_load(self, pages: list[str], n: int = 5) -> list[BenchmarkResult]:
        """
        Benchmark page load times.
        PRD Target: <2 seconds page load
        """
        print(f"\n📄 Benchmarking page load times ({len(pages)} pages, {n} iterations each)...")

        results = []

        for page in pages:
            latencies = []

            for i in range(n):
                start = time.monotonic()
                try:
                    response = await self.client.load_page(page)
                    elapsed = time.monotonic() - start

                    if response.status_code in [200, 304]:
                        latencies.append(elapsed)
                    else:
                        print(f"  {page}: HTTP {response.status_code}")

                except Exception as e:
                    print(f"  {page}: Error - {e}")

            if latencies:
                p50 = statistics.median(latencies)
                result = BenchmarkResult(
                    name=f"Page Load: {page}",
                    value=p50,
                    unit="s",
                    target=TARGETS["page_load"],
                    passed=p50 < TARGETS["page_load"],
                    details={
                        "p50": f"{p50:.3f}s",
                        "samples": len(latencies),
                    },
                )
                self.report.add_result(result)
                results.append(result)
                print(f"  {page}: {p50:.3f}s ({'✓' if result.passed else '✗'})")

        return results

    async def benchmark_concurrent_users(self, n_users: int = 5) -> BenchmarkResult:
        """
        Benchmark concurrent user performance.
        PRD Target: 5 simultaneous users without degradation
        """
        print(f"\n👥 Benchmarking concurrent users ({n_users} simultaneous)...")

        async def single_user_workflow(user_id: int) -> dict:
            """Simulate a single user's workflow"""
            results = {"user_id": user_id, "search_times": [], "chat_times": [], "errors": []}

            async with SOWKNOWClient(self.client.base_url) as client:
                # Note: In production, each user would have their own credentials
                # For this test, we use the same authenticated session
                client.cookies = self.client.cookies

                try:
                    # Search operation
                    start = time.monotonic()
                    search_resp = await client.search("solar energy documents")
                    search_time = time.monotonic() - start
                    results["search_times"].append(search_time)

                    # List documents operation
                    start = time.monotonic()
                    docs_resp = await client.list_documents(limit=10)
                    list_time = time.monotonic() - start
                    results["search_times"].append(list_time)

                    # Get current user info
                    me_resp = await client._request("GET", "/auth/me")

                except Exception as e:
                    results["errors"].append(str(e))

            return results

        # Run concurrent workflows
        start = time.monotonic()
        tasks = [single_user_workflow(i) for i in range(n_users)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.monotonic() - start

        # Analyze results
        all_search_times = []
        total_errors = 0

        for r in results:
            if isinstance(r, Exception):
                total_errors += 1
            else:
                all_search_times.extend(r.get("search_times", []))
                total_errors += len(r.get("errors", []))

        if all_search_times:
            avg_search = statistics.mean(all_search_times)
            # Check if concurrent performance is within 2x of single-user performance
            degradation_ok = avg_search < TARGETS["search_latency_p50"] * 2
        else:
            avg_search = 0
            degradation_ok = False

        result = BenchmarkResult(
            name="Concurrent Users",
            value=n_users,
            unit="users",
            target=TARGETS["concurrent_users"],
            passed=len(results) == n_users and total_errors == 0 and degradation_ok,
            details={
                "concurrent_users": n_users,
                "total_time": f"{total_time:.3f}s",
                "avg_search_time": f"{avg_search:.3f}s" if all_search_times else "N/A",
                "errors": total_errors,
                "degradation_ok": degradation_ok,
            },
        )
        self.report.add_result(result)

        print(f"  {n_users} users completed in {total_time:.3f}s")
        print(f"  Errors: {total_errors}")
        print(f"  Avg search time: {avg_search:.3f}s")

        return result

    async def benchmark_api_health(self) -> BenchmarkResult:
        """Check API health endpoint"""
        print("\n🏥 Checking API health...")

        try:
            start = time.monotonic()
            # Health endpoint is at /health, not under /api/v1
            response = await self.client.client.get(f"{self.client.base_url}/health")
            elapsed = time.monotonic() - start

            if response.status_code == 200:
                health_data = response.json()
                result = BenchmarkResult(
                    name="API Health Check",
                    value=elapsed,
                    unit="s",
                    target=1.0,
                    passed=True,
                    details={"response": health_data},
                )
                print(f"  Health check passed in {elapsed:.3f}s")
            else:
                result = BenchmarkResult(
                    name="API Health Check",
                    value=0,
                    unit="s",
                    target=1.0,
                    passed=False,
                    details={"status_code": response.status_code},
                )
                print(f"  Health check failed: HTTP {response.status_code}")

        except Exception as e:
            result = BenchmarkResult(
                name="API Health Check",
                value=0,
                unit="s",
                target=1.0,
                passed=False,
                details={"error": str(e)},
            )
            print(f"  Health check error: {e}")

        self.report.add_result(result)
        return result


async def run_audit(
    base_url: str,
    email: str,
    password: str,
    skip_chat: bool = False,
    skip_upload: bool = True,
    search_iterations: int = 10,
    chat_iterations: int = 5,
) -> AuditReport:
    """Run the complete performance audit"""

    environment = "custom"
    for env, url in ENVIRONMENTS.items():
        if base_url == url:
            environment = env
            break

    report = AuditReport(
        timestamp=datetime.now().isoformat(),
        environment=environment,
        base_url=base_url,
    )

    async with SOWKNOWClient(base_url) as client:
        # Login
        print(f"\n{'='*60}")
        print(f"SOWKNOW Performance Audit")
        print(f"{'='*60}")
        print(f"Base URL: {base_url}")

        if not await client.login(email, password):
            print("\n✗ Authentication failed. Cannot continue audit.")
            return report

        auditor = PerformanceAuditor(client, report)

        # Run benchmarks
        await auditor.benchmark_api_health()
        await auditor.benchmark_search(TEST_SEARCH_QUERIES, n=search_iterations)

        if not skip_chat:
            await auditor.benchmark_chat_first_token(n=chat_iterations)

        await auditor.benchmark_page_load(TEST_PAGES, n=3)
        await auditor.benchmark_concurrent_users(n_users=5)

        # Logout
        await client.logout()

    return report


def parse_args():
    parser = argparse.ArgumentParser(
        description="SOWKNOW Performance Audit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/performance_audit.py --env local
    python scripts/performance_audit.py --env production
    python scripts/performance_audit.py --base-url http://localhost:8000
    python scripts/performance_audit.py --env local --skip-chat
        """,
    )

    parser.add_argument(
        "--env",
        choices=["local", "production"],
        default="local",
        help="Target environment (default: local)",
    )
    parser.add_argument(
        "--base-url",
        help="Override base URL (e.g., http://localhost:8000)",
    )
    parser.add_argument(
        "--email",
        help="Login email (or set SOWKNOW_EMAIL env var)",
    )
    parser.add_argument(
        "--password",
        help="Login password (or set SOWKNOW_PASSWORD env var, or will prompt)",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Skip chat benchmarks (useful for quick tests)",
    )
    parser.add_argument(
        "--search-iterations",
        type=int,
        default=10,
        help="Number of search queries to benchmark (default: 10)",
    )
    parser.add_argument(
        "--chat-iterations",
        type=int,
        default=5,
        help="Number of chat messages to benchmark (default: 5)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Save report to JSON file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON only",
    )

    return parser.parse_args()


async def main():
    args = parse_args()

    # Determine base URL
    base_url = args.base_url or ENVIRONMENTS.get(args.env, ENVIRONMENTS["local"])

    # Get credentials
    email = args.email or os.environ.get("SOWKNOW_EMAIL") or os.environ.get("SOWKNOW_ADMIN_EMAIL")
    password = args.password or os.environ.get("SOWKNOW_PASSWORD") or os.environ.get("SOWKNOW_ADMIN_PASSWORD")

    if not email:
        email = input("Email: ")

    if not password:
        password = getpass.getpass("Password: ")

    # Run audit
    report = await run_audit(
        base_url=base_url,
        email=email,
        password=password,
        skip_chat=args.skip_chat,
        search_iterations=args.search_iterations,
        chat_iterations=args.chat_iterations,
    )

    # Output results
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        report.print_summary()

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nReport saved to: {output_path}")

    # Exit with appropriate code
    sys.exit(0 if report.failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
