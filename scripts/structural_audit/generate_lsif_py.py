#!/usr/bin/env python3
"""
Python LSIF Generator for Sowknow Backend

Generates a Language Server Index Format (LSIF) JSON dump from Python AST.
This enables precise code navigation in Sourcegraph, GitHub, and compatible tools.

LSIF spec: https://microsoft.github.io/language-server-protocol/specifications/lsif/0.6.0/specification/
"""

import ast
import json
import os
from pathlib import Path

BACKEND_ROOT = Path("/home/development/src/active/sowknow4/backend/app")
OUTPUT_DIR = Path("/home/development/src/active/sowknow4/.context/scip")
OUTPUT_FILE = OUTPUT_DIR / "backend.lsif"


def generate_lsif() -> list[dict]:
    """Generate LSIF vertices and edges for the Python backend."""
    elements: list[dict] = []
    id_counter = 1

    def next_id() -> int:
        nonlocal id_counter
        id_counter += 1
        return id_counter - 1

    # Project vertex
    project_id = next_id()
    elements.append({
        "id": project_id,
        "type": "vertex",
        "label": "project",
        "kind": "python",
    })

    python_files = sorted(BACKEND_ROOT.rglob("*.py"))

    for file_path in python_files:
        rel_path = file_path.relative_to(Path("/home/development/src/active/sowknow4"))
        rel_path_str = str(rel_path)

        # Document vertex
        doc_id = next_id()
        elements.append({
            "id": doc_id,
            "type": "vertex",
            "label": "document",
            "uri": f"file://{file_path}",
            "languageId": "python",
        })

        # contains edge: project -> document
        elements.append({
            "id": next_id(),
            "type": "edge",
            "label": "contains",
            "outV": project_id,
            "inVs": [doc_id],
        })

        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError:
            continue

        # Collect definition ranges and references
        definition_ranges = []
        reference_ranges = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Function definition
                line = node.lineno - 1
                col = node.col_offset
                name_len = len(node.name)
                range_id = next_id()
                elements.append({
                    "id": range_id,
                    "type": "vertex",
                    "label": "range",
                    "start": {"line": line, "character": col},
                    "end": {"line": line, "character": col + name_len},
                })
                definition_ranges.append(range_id)

                # resultSet
                rs_id = next_id()
                elements.append({
                    "id": rs_id,
                    "type": "vertex",
                    "label": "resultSet",
                })

                # next edge: range -> resultSet
                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "next",
                    "outV": range_id,
                    "inV": rs_id,
                })

                # definitionResult
                def_result_id = next_id()
                elements.append({
                    "id": def_result_id,
                    "type": "vertex",
                    "label": "definitionResult",
                })

                # definition edge: resultSet -> definitionResult
                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "definition",
                    "outV": rs_id,
                    "inV": def_result_id,
                })

                # item edge: definitionResult -> range
                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "item",
                    "outV": def_result_id,
                    "inVs": [range_id],
                    "document": doc_id,
                })

                # hoverResult
                hover_id = next_id()
                sig = f"def {node.name}({', '.join(a.arg for a in node.args.args)})"
                elements.append({
                    "id": hover_id,
                    "type": "vertex",
                    "label": "hoverResult",
                    "result": {
                        "contents": {"kind": "markdown", "value": f"```python\n{sig}\n```"},
                    },
                })

                # hover edge: resultSet -> hoverResult
                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "hover",
                    "outV": rs_id,
                    "inV": hover_id,
                })

            elif isinstance(node, ast.ClassDef):
                # Class definition
                line = node.lineno - 1
                col = node.col_offset
                name_len = len(node.name)
                range_id = next_id()
                elements.append({
                    "id": range_id,
                    "type": "vertex",
                    "label": "range",
                    "start": {"line": line, "character": col},
                    "end": {"line": line, "character": col + name_len},
                })
                definition_ranges.append(range_id)

                rs_id = next_id()
                elements.append({
                    "id": rs_id,
                    "type": "vertex",
                    "label": "resultSet",
                })

                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "next",
                    "outV": range_id,
                    "inV": rs_id,
                })

                def_result_id = next_id()
                elements.append({
                    "id": def_result_id,
                    "type": "vertex",
                    "label": "definitionResult",
                })

                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "definition",
                    "outV": rs_id,
                    "inV": def_result_id,
                })

                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "item",
                    "outV": def_result_id,
                    "inVs": [range_id],
                    "document": doc_id,
                })

                methods = ", ".join(m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
                hover_id = next_id()
                elements.append({
                    "id": hover_id,
                    "type": "vertex",
                    "label": "hoverResult",
                    "result": {
                        "contents": {"kind": "markdown", "value": f"```python\nclass {node.name}\n# methods: {methods}\n```"},
                    },
                })

                elements.append({
                    "id": next_id(),
                    "type": "edge",
                    "label": "hover",
                    "outV": rs_id,
                    "inV": hover_id,
                })

        # contains edge: document -> ranges
        if definition_ranges:
            elements.append({
                "id": next_id(),
                "type": "edge",
                "label": "contains",
                "outV": doc_id,
                "inVs": definition_ranges,
            })

    return elements


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    elements = generate_lsif()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for elem in elements:
            f.write(json.dumps(elem, separators=(",", ":")) + "\n")

    print(f"✅ Python LSIF generated: {OUTPUT_FILE}")
    print(f"   Vertices+Edges: {len(elements)}")
    print(f"   Size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
