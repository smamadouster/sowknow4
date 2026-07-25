"""Validate all runbook YAML files: parseable, internally consistent, and
any embedded `python3 -c` snippets must parse and use no undefined names.

Regression: celery_completion's check_probe_import step shipped with
`print(ok)` (bare name) — every execution raised NameError and the runbook
always routed to its terminal alert, never reaching the restart logic.
"""

import ast
import builtins
import shlex
from pathlib import Path

import yaml

RUNBOOKS_DIR = Path(__file__).resolve().parent.parent / "runbooks"


def _load_runbooks():
    files = sorted(RUNBOOKS_DIR.glob("*.yml"))
    assert files, f"no runbooks found in {RUNBOOKS_DIR}"
    return [(f.name, yaml.safe_load(f.read_text())) for f in files]


RUNBOOKS = _load_runbooks()


def test_runbooks_parse_and_have_steps():
    for fname, doc in RUNBOOKS:
        assert isinstance(doc, dict), fname
        assert doc.get("name"), fname
        steps = doc.get("steps")
        assert isinstance(steps, list) and steps, fname
        for step in steps:
            assert step.get("id"), f"{fname}: step without id"
            assert step.get("action"), f"{fname}: step {step.get('id')} without action"


def test_runbook_step_transitions_resolve():
    for fname, doc in RUNBOOKS:
        steps = doc["steps"]
        ids = [s["id"] for s in steps]
        assert len(set(ids)) == len(ids), f"{fname}: duplicate step ids"
        known = set(ids)
        for step in steps:
            for key in ("on_success", "on_failure"):
                target = step.get(key)
                if target is None:
                    continue
                assert target == "next" or target in known, (
                    f"{fname}: step {step['id']} {key} -> unknown step {target!r}"
                )


def _python_snippets(command: str):
    """Yield the source string of every `python3 -c <src>` in a shell command."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return
    for i, tok in enumerate(tokens):
        if tok in ("python", "python3") and tokens[i + 1 : i + 2] == ["-c"]:
            if i + 2 < len(tokens):
                yield tokens[i + 2]


def _undefined_names(tree: ast.AST) -> set:
    bound = set(dir(builtins))

    def bind_target(target):
        for t in ast.walk(target):
            if isinstance(t, ast.Name):
                bound.add(t.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                bind_target(target)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            args = node.args
            for a in args.posonlyargs + args.args + args.kwonlyargs:
                bound.add(a.arg)
            for a in (args.vararg, args.kwarg):
                if a is not None:
                    bound.add(a.arg)
        elif isinstance(node, ast.Lambda):
            for a in node.args.args:
                bound.add(a.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.For):
            bind_target(node.target)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    bind_target(item.optional_vars)
        elif isinstance(node, ast.comprehension):
            bind_target(node.target)
        elif isinstance(node, ast.NamedExpr):
            bind_target(node.target)
    undefined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in bound:
                undefined.add(node.id)
    return undefined


def test_embedded_python_snippets_are_valid():
    checked = 0
    for fname, doc in RUNBOOKS:
        for step in doc["steps"]:
            if step.get("action") != "exec" or "command" not in step:
                continue
            for src in _python_snippets(str(step["command"])):
                checked += 1
                where = f"{fname}:{step['id']}"
                tree = ast.parse(src, filename=where)  # raises SyntaxError
                undefined = _undefined_names(tree)
                assert not undefined, (
                    f"{where}: python snippet uses undefined name(s): "
                    f"{sorted(undefined)}"
                )
    assert checked > 0, "no python snippets found in any runbook"
