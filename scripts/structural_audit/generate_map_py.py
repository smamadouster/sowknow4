#!/usr/bin/env python3
"""
Python Architecture Mapper for Sowknow Backend
Generates cache.graph.backend.py using AST parsing.
"""
import ast
import os
import sys
from pathlib import Path
from collections import defaultdict

BACKEND_ROOT = Path("/home/development/src/active/sowknow4/backend/app")
OUTPUT_DIR = Path("/home/development/src/active/sowknow4/scripts/structural_audit")
OUTPUT_FILE = OUTPUT_DIR / "cache.graph.backend.py"

hub_tracker = defaultdict(int)

def extract_imports(node: ast.AST) -> tuple[list[str], list[str]]:
    """Extract local and external imports from an AST node."""
    local_deps = []
    ext_deps = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                name = alias.name.split('.')[0]
                ext_deps.append(name)
        elif isinstance(child, ast.ImportFrom):
            module = child.module or ""
            if module.startswith("app.") or module.startswith("."):
                local_deps.append(module)
            else:
                ext_deps.append(module.split('.')[0])
    return local_deps, ext_deps

def extract_definitions(node: ast.AST) -> list[str]:
    """Extract function/class definitions from AST."""
    defs = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef):
            params = [arg.arg for arg in child.args.args]
            defs.append(f"[fn]: {child.name}({', '.join(params)})")
        elif isinstance(child, ast.AsyncFunctionDef):
            params = [arg.arg for arg in child.args.args]
            defs.append(f"[async_fn]: {child.name}({', '.join(params)})")
        elif isinstance(child, ast.ClassDef):
            methods = []
            for item in child.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(item.name)
            defs.append(f"[class]: {child.name} {{ methods: [{', '.join(methods)}] }}")
    return defs

def main():
    map_content = '"""\n🧠 BACKEND ARCHITECTURE MAP (Auto-generated via Python AST)\n"""\n\n'
    
    python_files = list(BACKEND_ROOT.rglob("*.py"))
    
    for file_path in sorted(python_files):
        rel_path = file_path.relative_to(Path("/home/development/src/active/sowknow4"))
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError as e:
            map_content += f"# SYNTAX ERROR in {rel_path}: {e}\n\n"
            continue
        
        map_content += f"### FILE: {rel_path}\n"
        
        local_deps, ext_deps = extract_imports(tree)
        if local_deps:
            map_content += f"[local_deps]: {', '.join(set(local_deps))}\n"
            for dep in set(local_deps):
                hub_tracker[dep] += 1
        if ext_deps:
            map_content += f"[ext_deps]: {', '.join(set(ext_deps))}\n"
        
        defs = extract_definitions(tree)
        if defs:
            map_content += "\n".join(defs) + "\n"
        
        map_content += "\n---\n"
    
    # Hub analysis
    top_hubs = sorted(hub_tracker.items(), key=lambda x: x[1], reverse=True)[:10]
    hub_header = '"""\n🧠 TOP ARCHITECTURAL HUBS (Most Imported Local Modules)\n' + \
        "\n".join([f"# [hub]: {mod} → imported {count} times" for mod, count in top_hubs]) + \
        '\n"""\n\n'
    
    map_content = hub_header + map_content
    
    OUTPUT_FILE.write_text(map_content, encoding="utf-8")
    print("✅ Backend cache.graph.backend.py generated successfully.")
    if top_hubs:
        print(f"📊 Top Hub: {top_hubs[0][0]} ({top_hubs[0][1]} imports)")

if __name__ == "__main__":
    main()
