#!/usr/bin/env python3
"""
SOWKNOW Search QA Orchestrator

Runs the complete QA validation suite across all phases and generates
a Markdown report suitable for commit gates.

Usage:
    python scripts/run_search_qa.py [--output report.md]

Exit codes:
    0 = all gates passed
    1 = one or more gates failed
"""

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QAResult:
    name: str
    passed: bool
    duration_ms: float
    details: str = ""
    phase: str = ""


@dataclass
class QAReport:
    timestamp: str
    results: list[QAResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)


def run_pytest(test_path: str, markers: str = "") -> QAResult:
    """Run a pytest file and capture result."""
    name = Path(test_path).stem
    cmd = ["python3", "-m", "pytest", test_path, "-v", "--tb=short", "-q"]
    if markers:
        cmd.extend(["-m", markers])

    start = time.time()
    proc = subprocess.run(
        cmd,
        cwd=Path(__file__).parent.parent / "backend",
        capture_output=True,
        text=True,
    )
    elapsed = (time.time() - start) * 1000

    passed = proc.returncode == 0
    details = proc.stdout + proc.stderr
    return QAResult(name=name, passed=passed, duration_ms=elapsed, details=details)


def run_backend_syntax_check() -> QAResult:
    """Verify all modified backend files compile."""
    files = [
        "backend/app/api/search_suggest.py",
        "backend/app/api/search_feedback.py",
        "backend/app/services/search_cache.py",
        "backend/app/services/search_service.py",
        "backend/app/services/search_agent.py",
        "backend/app/services/rerank_service.py",
        "backend/app/services/spell_service.py",
        "backend/app/api/search_agent_router.py",
        "backend/app/main.py",
    ]

    start = time.time()
    cmd = ["python3", "-m", "py_compile"] + files
    proc = subprocess.run(cmd, cwd=Path(__file__).parent.parent, capture_output=True, text=True)
    elapsed = (time.time() - start) * 1000

    return QAResult(
        name="backend_syntax_check",
        passed=proc.returncode == 0,
        duration_ms=elapsed,
        details=proc.stderr if proc.returncode != 0 else "All files compile cleanly",
    )


def run_frontend_tsc() -> QAResult:
    """Run TypeScript compiler check."""
    start = time.time()
    proc = subprocess.run(
        ["npx", "tsc", "--noEmit", "--pretty", "false"],
        cwd=Path(__file__).parent.parent / "frontend",
        capture_output=True,
        text=True,
    )
    elapsed = (time.time() - start) * 1000

    return QAResult(
        name="frontend_typescript_check",
        passed=proc.returncode == 0,
        duration_ms=elapsed,
        details=proc.stdout if proc.returncode != 0 else "TypeScript compiles with zero errors",
    )


def run_import_checks() -> QAResult:
    """Verify key modules import without errors."""
    start = time.time()
    imports = [
        "from app.api import search_suggest, search_feedback",
        "from app.services import search_cache, rerank_service, spell_service",
        "from app.services.search_service import HybridSearchService, _get_regconfig",
        "from app.services.search_agent import run_agentic_search",
    ]

    cmd = ["python3", "-c", "; ".join(imports)]
    proc = subprocess.run(cmd, cwd=Path(__file__).parent.parent / "backend", capture_output=True, text=True)
    elapsed = (time.time() - start) * 1000

    return QAResult(
        name="backend_import_check",
        passed=proc.returncode == 0,
        duration_ms=elapsed,
        details=proc.stderr if proc.returncode != 0 else "All imports succeed",
    )


def generate_report(report: QAReport, output_path: Path) -> None:
    """Write QA report as Markdown."""
    lines = [
        "# SOWKNOW Search QA Validation Report",
        f"**Generated:** {report.timestamp}",
        f"**Overall:** {'✅ ALL GATES PASSED' if report.all_passed else '❌ SOME GATES FAILED'}",
        "",
        f"| Phase | Test | Status | Duration |",
        f"|-------|------|--------|----------|",
    ]

    for r in report.results:
        icon = "✅" if r.passed else "❌"
        phase = r.phase or "General"
        lines.append(f"| {phase} | {r.name} | {icon} | {r.duration_ms:.0f}ms |")

    lines.extend([
        "",
        "## Summary",
        f"- **Passed:** {report.pass_count}",
        f"- **Failed:** {report.fail_count}",
        f"- **Total:** {len(report.results)}",
        "",
        "## Details",
    ])

    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        lines.extend([
            f"### {r.name} ({status})",
            f"```",
            r.details[:2000] if r.details else "(no output)",
            f"```",
            "",
        ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="SOWKNOW Search QA Orchestrator")
    parser.add_argument("--output", default="docs/SEARCH_QA_REPORT.md", help="Output markdown path")
    parser.add_argument("--skip-postgres", action="store_true", help="Skip tests requiring PostgreSQL")
    args = parser.parse_args()

    report = QAReport(timestamp=time.strftime("%Y-%m-%d %H:%M:%S %Z"))

    print("=" * 60)
    print("SOWKNOW SEARCH QA VALIDATION")
    print("=" * 60)

    # Gate 1: Syntax / Static Analysis
    print("\n[Gate 1] Backend syntax check...")
    r = run_backend_syntax_check()
    report.results.append(r)
    print(f"  {'✅' if r.passed else '❌'} {r.name} ({r.duration_ms:.0f}ms)")

    print("\n[Gate 2] Frontend TypeScript check...")
    r = run_frontend_tsc()
    report.results.append(r)
    print(f"  {'✅' if r.passed else '❌'} {r.name} ({r.duration_ms:.0f}ms)")

    print("\n[Gate 3] Backend import check...")
    r = run_import_checks()
    report.results.append(r)
    print(f"  {'✅' if r.passed else '❌'} {r.name} ({r.duration_ms:.0f}ms)")

    # Gate 4: Phase 1 QA
    print("\n[Gate 4] Phase 1 QA (Quick Wins)...")
    r = run_pytest("../backend/tests/qa/test_search_phase1_qa.py")
    r.phase = "Phase 1"
    report.results.append(r)
    print(f"  {'✅' if r.passed else '❌'} {r.name} ({r.duration_ms:.0f}ms)")

    # Gate 5: Phase 2 QA
    print("\n[Gate 5] Phase 2 QA (Accuracy)...")
    r = run_pytest("../backend/tests/qa/test_search_phase2_qa.py")
    r.phase = "Phase 2"
    report.results.append(r)
    print(f"  {'✅' if r.passed else '❌'} {r.name} ({r.duration_ms:.0f}ms)")

    # Gate 6: Phase 3 QA
    print("\n[Gate 6] Phase 3 QA (Advanced)...")
    r = run_pytest("../backend/tests/qa/test_search_phase3_qa.py")
    r.phase = "Phase 3"
    report.results.append(r)
    print(f"  {'✅' if r.passed else '❌'} {r.name} ({r.duration_ms:.0f}ms)")

    # Gate 7: Performance (requires Postgres)
    if not args.skip_postgres:
        print("\n[Gate 7] Performance benchmarks...")
        r = run_pytest("../backend/tests/qa/test_search_performance_qa.py", markers="benchmark")
        r.phase = "Performance"
        report.results.append(r)
        print(f"  {'✅' if r.passed else '❌'} {r.name} ({r.duration_ms:.0f}ms)")
    else:
        print("\n[Gate 7] Performance benchmarks skipped (--skip-postgres)")
        report.results.append(QAResult(
            name="performance_benchmarks", passed=True,
            duration_ms=0, details="Skipped (--skip-postgres)", phase="Performance"
        ))

    # Generate report
    print("\n" + "=" * 60)
    print(f"RESULT: {report.pass_count}/{len(report.results)} gates passed")
    print("=" * 60)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_report(report, output_path)

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
