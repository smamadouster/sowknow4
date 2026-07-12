#!/usr/bin/env python3
"""
Wiring completeness check for SOWKNOW.

Fails when:
- An API router is imported in main.py but never included.
- A Celery task module is referenced by the beat schedule but not loaded.
- A cron script calls a backend endpoint that is not registered.

Run locally:
    PYTHONPATH=backend python scripts/wiring_check.py
"""

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
APP_DIR = BACKEND_DIR / "app"


def _ast_imports(path: Path) -> list[str]:
    """Return a list of `from app.api import x` style names in a file."""
    names: list[str] = []
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.api":
            for alias in node.names:
                names.append(alias.asname or alias.name)
    return names


def _ast_include_calls(path: Path) -> list[str]:
    """Return router names passed to app.include_router(...) in a file."""
    names: list[str] = []
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                    names.append(arg.value.id)
    return names


def check_routers() -> list[str]:
    """Ensure every imported api module is include_router-ed."""
    main_path = APP_DIR / "main.py"
    imported = _ast_imports(main_path)
    included = _ast_include_calls(main_path)

    missing = [name for name in imported if name not in included]
    if missing:
        return [f"Router imported but not included in main.py: {missing}"]
    return []


def check_celery_modules() -> list[str]:
    """Ensure every beat-scheduled task module is in celery_app.conf.include."""
    celery_path = APP_DIR / "celery_app.py"
    source = celery_path.read_text()

    include_match = re.search(r"include\s*=\s*\[(.*?)\]", source, re.DOTALL)
    if not include_match:
        return ["Could not parse celery_app.conf.include"]

    included = set(m.strip('"\'') for m in re.findall(r'"([^"]+)"', include_match.group(1)))

    beat_match = re.search(r"beat_schedule\s*=\s*\{(.*?)\}\s*,?\s*$", source, re.DOTALL | re.MULTILINE)
    if not beat_match:
        return ["Could not parse celery_app.conf.beat_schedule"]

    scheduled_tasks = re.findall(r'"task"\s*:\s*"([^"]+)"', beat_match.group(1))
    errors = []
    for task in scheduled_tasks:
        module = task.rsplit(".", 1)[0]
        # Tasks named "pipeline.*" are registered by pipeline_orchestrator / pipeline_sweeper.
        if module == "pipeline":
            if "app.tasks.pipeline_orchestrator" not in included and "app.tasks.pipeline_sweeper" not in included:
                errors.append(f"Beat task {task!r} requires pipeline_orchestrator or pipeline_sweeper in include")
            continue
        if module not in included:
            errors.append(f"Beat task {task!r} module {module!r} is not in celery_app.conf.include")
    return errors


def _collect_registered_routes() -> set[str]:
    """Collect all route paths registered under /api/v1."""
    routes: set[str] = set()
    main_path = APP_DIR / "main.py"
    main_source = main_path.read_text()

    # Find include_router(prefix="/api/v1") calls and the module name being included
    # Then scan the included module for @router.get("/...") decorators.
    include_re = re.compile(
        r'app\.include_router\(\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\.router\s*,\s*prefix\s*=\s*"(/api/v1)"\s*\)'
    )
    api_files = {p.stem: p for p in APP_DIR.glob("api/**/*.py")}

    for match in include_re.finditer(main_source):
        module_path = match.group(1)
        prefix = match.group(2)
        module_name = module_path.split(".")[-1]
        file_path = api_files.get(module_name)
        if not file_path:
            continue
        file_source = file_path.read_text()
        for route in re.findall(r'@router\.(get|post|put|delete|patch)\(\s*"([^"]+)"', file_source):
            routes.add(f"{prefix}{route[1]}")
    return routes


def check_cron_endpoints() -> list[str]:
    """Ensure endpoints called by scripts/*.sh are registered."""
    registered = _collect_registered_routes()
    errors = []
    for script in (PROJECT_ROOT / "scripts").glob("*.sh"):
        for url in re.findall(r'\$\{API_URL\}(/api/v1/[^"\'\s`]+)', script.read_text()):
            # Strip query strings for comparison
            clean_url = url.split("?")[0]
            if clean_url not in registered:
                errors.append(f"{script.name} calls unregistered endpoint {clean_url}")
    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(check_routers())
    errors.extend(check_celery_modules())
    errors.extend(check_cron_endpoints())

    if errors:
        print("Wiring check FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("Wiring check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
