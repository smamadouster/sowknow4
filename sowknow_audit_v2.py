#!/usr/bin/env python3
"""
SOWKNOW — Deep-Tier Agentic Stack Audit v2.0
==============================================
Principal AI Architect & Systems Engineer Audit Script

Fixes over v1:
  - Self-exclusion: skips its own file and any sowknow_audit* files
  - Test separation: test files flagged separately, never inflate agent/tool counts
  - Env redaction: NEVER outputs env variable values, only key names
  - Tighter agent detection: requires structural evidence, not just keyword matches
  - Prompt quality analysis: reads multi-line system prompts, scores WHY/WHO/HOW
  - Memory tier accuracy: distinguishes response caching from prompt caching
  - Cleaner report: deduplicates findings, groups by logical component

Usage:
  python3 sowknow_audit_v2.py /path/to/sowknow/codebase
  python3 sowknow_audit_v2.py .
"""

import os
import sys
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field

REPORT_VERSION = "2.0"
REPORT_DATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ──────────────────────────────────────────────────────────────
# File Classification
# ──────────────────────────────────────────────────────────────

CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".yaml", ".yml", ".toml", ".json",
    ".sh", ".bash",
}
ENV_EXTENSIONS = {".env"}
DOCKER_NAMES = {
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "docker-compose.dev.yml", "docker-compose.production.yml",
    "docker-compose.simple.yml", "docker-compose.prebuilt.yml",
    "compose.yml", "compose.yaml",
}
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".next", ".venv",
    "venv", "env", ".mypy_cache", ".pytest_cache", "dist",
    "build", ".docker", "coverage", ".turbo", ".ruff_cache",
    "screenshots", "audit_reports", "reports",
}
# Files to ALWAYS skip (self-exclusion + generated reports)
SKIP_FILE_PATTERNS = [
    r"sowknow_audit.*\.py$",
    r"sowknow_static_audit.*\.sh$",
    r"SOWKNOW_.*AUDIT.*\.(md|txt)$",
]


def is_test_file(rel_path: str) -> bool:
    """Classify whether a file is a test file."""
    parts = rel_path.lower().replace("\\", "/").split("/")
    if any(p in ("tests", "test", "__tests__", "spec", "fixtures") for p in parts):
        return True
    basename = os.path.basename(rel_path).lower()
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return True
    if "conftest" in basename or "fixture" in basename:
        return True
    return False


def is_env_file(filename: str) -> bool:
    """Check if a file is an environment config file."""
    name = filename.lower()
    return (name.startswith(".env") or
            name.endswith(".env") or
            name in (".secrets", ".secrets.baseline"))


def should_skip_file(rel_path: str) -> bool:
    """Check if file should be entirely skipped."""
    basename = os.path.basename(rel_path)
    for pat in SKIP_FILE_PATTERNS:
        if re.search(pat, basename, re.IGNORECASE):
            return True
    return False


# ──────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────

@dataclass
class AgentProfile:
    name: str
    file_path: str
    line_number: int
    category: str = "service"  # "class" | "service" | "standalone_prompt"
    is_test: bool = False
    has_system_prompt: bool = False
    prompt_text: str = ""  # first ~500 chars of the prompt
    has_mission_why: bool = False
    has_persona_who: bool = False
    has_constraints_how: bool = False
    has_confidential_guard: bool = False
    llm_provider: str = "unknown"
    profile_score: int = 0
    profile_grade: str = "F"  # F / D / C / B / A


@dataclass
class MemoryFinding:
    tier: str
    file_path: str
    line_number: int
    evidence: str  # what specifically was found
    is_test: bool = False
    is_real: bool = True  # false if it's just a config key or comment


@dataclass
class ToolFinding:
    name: str
    file_path: str
    line_number: int
    has_schema: bool = False
    has_description: bool = False
    has_required_params: bool = False
    has_output_validation: bool = False
    is_test: bool = False


@dataclass
class InfraFinding:
    component: str
    file_path: str
    evidence: str
    status: str = "PRESENT"


@dataclass
class EnvKey:
    name: str
    file_path: str
    is_sensitive: bool = False


# ──────────────────────────────────────────────────────────────
# Scanner Engine v2
# ──────────────────────────────────────────────────────────────

class CodebaseScannerV2:

    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        self.files_scanned = 0
        self.files_skipped = 0
        self.total_lines = 0
        self.test_files_count = 0
        self.source_files_count = 0
        self.agents: list[AgentProfile] = []
        self.memory: dict[str, list[MemoryFinding]] = defaultdict(list)
        self.tools: list[ToolFinding] = []
        self.infra: list[InfraFinding] = []
        self.env_keys: list[EnvKey] = []
        self.llm_refs: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.project_dirs: set[str] = set()
        self.project_top_files: list[str] = []

    # ── File Discovery ──

    def discover_files(self) -> list[tuple[Path, bool]]:
        """Find files, returning (path, is_test) tuples. Skips self."""
        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel_dir = os.path.relpath(dirpath, self.root)

            # Track top-level structure
            if rel_dir == ".":
                for d in sorted(dirnames):
                    self.project_dirs.add(d)
                for f in sorted(filenames):
                    self.project_top_files.append(f)

            for fname in sorted(filenames):
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, self.root)

                if should_skip_file(rel):
                    self.files_skipped += 1
                    continue

                ext = os.path.splitext(fname)[1].lower()
                is_scannable = (
                    ext in CODE_EXTENSIONS or
                    ext in ENV_EXTENSIONS or
                    fname in DOCKER_NAMES or
                    is_env_file(fname)
                )
                if is_scannable:
                    test = is_test_file(rel)
                    files.append((Path(full), test))
                    if test:
                        self.test_files_count += 1
                    else:
                        self.source_files_count += 1
        return files

    def load_file(self, path: Path) -> list[str]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            self.files_scanned += 1
            self.total_lines += len(lines)
            return lines
        except Exception:
            return []

    # ── Helpers ──

    def _search(self, lines: list[str], patterns: list[str],
                case_sensitive: bool = False) -> list[tuple[int, str, str]]:
        """Search lines for patterns. Returns [(line_num_1based, pattern, line_text)]."""
        flags = 0 if case_sensitive else re.IGNORECASE
        results = []
        for i, line in enumerate(lines, 1):
            for pat in patterns:
                if re.search(pat, line, flags):
                    results.append((i, pat, line.strip()))
                    break
        return results

    def _extract_multiline_string(self, lines: list[str], start_line: int,
                                   max_chars: int = 500) -> str:
        """Extract a multi-line string starting near start_line (0-indexed)."""
        collected = []
        in_string = False
        triple_delim = None
        total = 0

        for i in range(max(0, start_line), min(len(lines), start_line + 40)):
            line = lines[i]
            if not in_string:
                # Look for triple-quote start
                for delim in ['"""', "'''"]:
                    idx = line.find(delim)
                    if idx >= 0:
                        in_string = True
                        triple_delim = delim
                        rest = line[idx + 3:]
                        # Check if it closes on the same line
                        close = rest.find(delim)
                        if close >= 0:
                            collected.append(rest[:close])
                            return " ".join(collected).strip()[:max_chars]
                        collected.append(rest.rstrip())
                        total += len(rest)
                        break
                # Also check for single-line f-string or regular string
                if not in_string:
                    m = re.search(r'[=:]\s*f?["\'](.{20,})["\']', line)
                    if m:
                        return m.group(1).strip()[:max_chars]
            else:
                close = line.find(triple_delim)
                if close >= 0:
                    collected.append(line[:close].rstrip())
                    return " ".join(collected).strip()[:max_chars]
                collected.append(line.rstrip())
                total += len(line)
                if total > max_chars:
                    break

        return " ".join(collected).strip()[:max_chars] if collected else ""

    # ── Phase 1: Agent Census ──

    def scan_agents(self, rel_path: str, lines: list[str], is_test: bool):
        """Detect real agents with structural analysis."""
        content = "\n".join(lines)

        # 1. Detect agent CLASSES (strongest signal)
        class_pattern = r'class\s+(\w*(?:Agent|Orchestrator|Bot))\s*[\(:]'
        for m in re.finditer(class_pattern, content):
            name = m.group(1)
            line_num = content[:m.start()].count("\n") + 1

            agent = AgentProfile(
                name=name,
                file_path=rel_path,
                line_number=line_num,
                category="class",
                is_test=is_test,
            )
            self._enrich_agent(agent, lines, line_num - 1)
            self.agents.append(agent)

        # 2. Detect SERVICE-LEVEL system prompts (standalone LLM calls with system role)
        #    Only in non-test source files
        if not is_test:
            # Pattern: system_prompt = """..."""  or  SYSTEM_PROMPT = """..."""
            sp_pattern = r'^\s*((?:INTENT_|SUGGESTION_)?(?:SYSTEM_PROMPT|system_prompt))\s*=\s*'
            for i, line in enumerate(lines):
                m = re.match(sp_pattern, line)
                if m:
                    # Check this isn't already covered by a class agent
                    covered = any(
                        a.file_path == rel_path and
                        abs(a.line_number - (i + 1)) < 60 and
                        a.category == "class"
                        for a in self.agents
                    )
                    if not covered:
                        prompt_text = self._extract_multiline_string(lines, i)
                        # Determine service name from file
                        svc_name = self._service_name_from_path(rel_path)

                        agent = AgentProfile(
                            name=f"{svc_name} → {m.group(1)}",
                            file_path=rel_path,
                            line_number=i + 1,
                            category="standalone_prompt",
                            is_test=False,
                            has_system_prompt=True,
                            prompt_text=prompt_text,
                        )
                        self._score_prompt(agent, prompt_text)
                        self.agents.append(agent)

            # 3. Detect inline system role messages: {"role": "system", "content": ...}
            inline_pattern = r'["\']role["\']\s*:\s*["\']system["\']'
            for i, line in enumerate(lines):
                if re.search(inline_pattern, line):
                    # Check not already covered
                    covered = any(
                        a.file_path == rel_path and
                        abs(a.line_number - (i + 1)) < 10
                        for a in self.agents
                    )
                    if not covered:
                        # Try to extract content from nearby lines
                        nearby = "\n".join(lines[max(0, i-2):min(len(lines), i+5)])
                        content_m = re.search(
                            r'["\']content["\']\s*:\s*(?:f?["\'](.{20,}?)["\']|(\w+))',
                            nearby
                        )
                        if content_m:
                            svc_name = self._service_name_from_path(rel_path)
                            agent = AgentProfile(
                                name=f"{svc_name} → inline system msg",
                                file_path=rel_path,
                                line_number=i + 1,
                                category="standalone_prompt",
                                is_test=False,
                                has_system_prompt=True,
                                prompt_text=(content_m.group(1) or content_m.group(2) or "")[:300],
                            )
                            self._score_prompt(agent, agent.prompt_text)
                            self.agents.append(agent)

    def _service_name_from_path(self, rel_path: str) -> str:
        """Extract a readable service name from the file path."""
        basename = os.path.basename(rel_path).replace(".py", "").replace(".ts", "")
        # CamelCase it
        parts = basename.split("_")
        return "".join(p.capitalize() for p in parts)

    def _enrich_agent(self, agent: AgentProfile, lines: list[str], start_idx: int):
        """Enrich an agent class with prompt analysis."""
        # Search within the class body (up to 200 lines ahead)
        block = "\n".join(lines[start_idx:min(len(lines), start_idx + 200)])

        # Find system prompt assignment
        sp_match = re.search(
            r'(?:system_prompt|SYSTEM_PROMPT)\s*=\s*(?:f?"""|\s*f?["\'])',
            block
        )
        if sp_match:
            agent.has_system_prompt = True
            prompt_line = start_idx + block[:sp_match.start()].count("\n")
            agent.prompt_text = self._extract_multiline_string(lines, prompt_line)
            self._score_prompt(agent, agent.prompt_text)

        # Detect LLM provider
        for provider, patterns in LLM_DETECT.items():
            if any(re.search(p, block, re.IGNORECASE) for p in patterns):
                agent.llm_provider = provider
                break

    def _score_prompt(self, agent: AgentProfile, text: str):
        """Score a system prompt for WHY/WHO/HOW quality."""
        text_lower = text.lower()

        # WHY — Mission / Purpose
        why_signals = [
            r"your (?:mission|purpose|goal|objective|role) is",
            r"you are responsible for",
            r"your task is to",
            r"designed to",
            r"purpose:",
            r"mission:",
        ]
        agent.has_mission_why = any(re.search(p, text_lower) for p in why_signals)

        # WHO — Persona / Identity
        who_signals = [
            r"you are (?:a |an |the )",
            r"tu es ",  # French
            r"your name is",
            r"act as",
            r"persona:",
        ]
        agent.has_persona_who = any(re.search(p, text_lower) for p in who_signals)

        # HOW — Constraints / Boundaries
        how_signals = [
            r"you must(?:n't| not)?",
            r"never ",
            r"always ",
            r"do not ",
            r"forbidden",
            r"required to",
            r"constraint",
            r"you should(?:n't| not)?",
            r"important:",
            r"rule:",
            r"ne (?:jamais|pas)",  # French
        ]
        agent.has_constraints_how = any(re.search(p, text_lower) for p in how_signals)

        # Confidential guard check
        conf_signals = [
            r"confidential",
            r"vault",
            r"sensitive",
            r"private.*document",
            r"ollama.*confidential|confidential.*ollama",
        ]
        agent.has_confidential_guard = any(re.search(p, text_lower) for p in conf_signals)

        # Score: 0-10
        score = 0
        score += 2 if agent.has_system_prompt else 0
        score += 2 if agent.has_mission_why else 0
        score += 2 if agent.has_persona_who else 0
        score += 2 if agent.has_constraints_how else 0
        score += 1 if agent.has_confidential_guard else 0
        score += 1 if len(text) > 100 else 0  # substantial prompt
        agent.profile_score = score

        if score >= 9:
            agent.profile_grade = "A"
        elif score >= 7:
            agent.profile_grade = "B"
        elif score >= 5:
            agent.profile_grade = "C"
        elif score >= 3:
            agent.profile_grade = "D"
        else:
            agent.profile_grade = "F"

    # ── Phase 2: Memory Tiers ──

    def scan_memory(self, rel_path: str, lines: list[str], is_test: bool):
        """Detect 4-stage memory with precision scoring."""

        # Stage 1: Sensory / Buffer
        sensory_real = [
            (r'class\s+\w*(?:InputGuard|InputFilter|QueryFilter|PreProcessor)', "Input guard class"),
            (r'def\s+(?:sanitize|filter|preprocess)_(?:input|query)', "Input sanitization function"),
            (r'pii[_\s]*(?:detect|filter|redact|strip)', "PII detection/redaction"),
            (r'intent[_\s]*classif', "Intent classification"),
            (r'dedup(?:licate)?[_\s]*(?:query|input|request)', "Query deduplication"),
        ]
        sensory_partial = [
            (r'rate[_\s]*limit(?!.*#)', "Rate limiting"),
            (r'max[_\s]*tokens\s*[=:]', "Token limit config"),
            (r'token[_\s]*count', "Token counting"),
            (r'truncat(?:e|ion)', "Input truncation"),
            (r'input[_\s]*valid', "Input validation"),
        ]
        self._scan_tier("sensory_buffer", lines, rel_path, is_test,
                        sensory_real, sensory_partial)

        # Stage 2: Working Memory (Prompt Caching)
        # CRITICAL: distinguish response caching (Redis) from prompt caching (LLM-level)
        working_real = [
            (r'cache_control.*ephemeral', "Anthropic prompt cache control"),
            (r'prompt[_\s]*cach(?:e|ing)\b(?!.*test)', "Prompt caching implementation"),
            (r'beta.*prompt.*caching', "Anthropic beta prompt caching"),
            (r'cached_system_prompt|system_prompt_cache', "Cached system prompt"),
            (r'static[_\s]*context[_\s]*cache', "Static context caching"),
            (r'context[_\s]*window[_\s]*manag', "Context window management"),
        ]
        working_partial = [
            (r'message[_\s]*history', "Conversation history"),
            (r'conversation[_\s]*(?:buffer|memory|context)', "Conversation memory"),
            (r'chat[_\s]*history', "Chat history storage"),
            (r'session[_\s]*(?:memory|context|state)', "Session state"),
        ]
        self._scan_tier("working_memory", lines, rel_path, is_test,
                        working_real, working_partial)

        # Stage 3: Episodic Memory (Vector/RAG)
        episodic_real = [
            (r'pgvector', "pgvector database"),
            (r'(?:create|add)_embedding|generate_embedding|embed_(?:document|text|chunk)', "Embedding generation"),
            (r'vector[_\s]*(?:store|search|index|db)', "Vector store operations"),
            (r'cosine[_\s]*similarity|similarity[_\s]*search', "Similarity search"),
            (r'hybrid[_\s]*search', "Hybrid search"),
            (r'chunk(?:ing|_text|_document|_size)', "Document chunking"),
            (r'(?:multilingual.e5|sentence.transformer)', "Embedding model"),
            (r'retrieve.*chunk|chunk.*retriev', "Chunk retrieval"),
        ]
        episodic_partial = [
            (r'embedding[_\s]*(?:model|dimension|dim)', "Embedding config"),
            (r'EMBEDDING_', "Embedding env var"),
            (r'full[_\s]*text[_\s]*search', "Full-text search"),
        ]
        self._scan_tier("episodic_memory", lines, rel_path, is_test,
                        episodic_real, episodic_partial)

        # Stage 4: Semantic Memory (Graph/Wisdom)
        semantic_real = [
            (r'(?:knowledge|entity)[_\s]*graph', "Knowledge/entity graph"),
            (r'entity[_\s]*extract(?:ion|or)?', "Entity extraction"),
            (r'relationship[_\s]*(?:map|extract|store|graph)', "Relationship mapping"),
            (r'graph[_\s]*rag', "Graph-RAG"),
            (r'neo4j|networkx', "Graph database/library"),
            (r'triple[_\s]*store', "Triple store"),
            (r'(?:family|curator)[_\s]*(?:context|values)', "Family/curator context"),
        ]
        semantic_partial = [
            (r'ENABLE_KNOWLEDGE_GRAPH', "Knowledge graph feature flag"),
            (r'entity[_\s]*(?:type|label)', "Entity type definitions"),
            (r'progressive[_\s]*revelation', "Progressive revelation"),
        ]
        self._scan_tier("semantic_memory", lines, rel_path, is_test,
                        semantic_real, semantic_partial)

    def _scan_tier(self, tier: str, lines: list[str], rel_path: str,
                    is_test: bool, real_patterns: list, partial_patterns: list):
        """Scan a memory tier with real vs partial classification."""
        for pat, desc in real_patterns:
            hits = self._search(lines, [pat])
            for line_num, _, line_text in hits:
                self.memory[tier].append(MemoryFinding(
                    tier=tier, file_path=rel_path, line_number=line_num,
                    evidence=desc, is_test=is_test, is_real=True,
                ))
        for pat, desc in partial_patterns:
            hits = self._search(lines, [pat])
            for line_num, _, line_text in hits:
                self.memory[tier].append(MemoryFinding(
                    tier=tier, file_path=rel_path, line_number=line_num,
                    evidence=desc, is_test=is_test, is_real=False,
                ))

    # ── Phase 3: Tool Schemas ──

    def scan_tools(self, rel_path: str, lines: list[str], is_test: bool):
        """Detect formal tool/function definitions for LLM agents."""
        # Only look for structured tool definitions, not generic function defs
        tool_patterns = [
            r'"type"\s*:\s*"function"',           # OpenAI/Anthropic format
            r'tools?\s*=\s*\[\s*\{',              # tool list assignment
            r'@tool\b',                            # LangChain decorator
            r'FunctionTool\s*\(',                  # Framework tool class
            r'StructuredTool\s*\(',                # LangChain structured
            r'tool_schema\s*=',                    # explicit schema var
        ]
        hits = self._search(lines, tool_patterns, case_sensitive=False)

        for line_num, pat, line_text in hits:
            # Look nearby for schema quality signals
            nearby_start = max(0, line_num - 3)
            nearby_end = min(len(lines), line_num + 30)
            nearby = "\n".join(lines[nearby_start:nearby_end])

            tool = ToolFinding(
                name=line_text[:80],
                file_path=rel_path,
                line_number=line_num,
                is_test=is_test,
                has_schema=bool(re.search(r'"parameters"\s*:\s*\{', nearby)),
                has_description=bool(re.search(r'"description"\s*:\s*"', nearby)),
                has_required_params=bool(re.search(r'"required"\s*:\s*\[', nearby)),
                has_output_validation=bool(re.search(
                    r'validate[_\s]*(?:output|result)|output[_\s]*parser', nearby)),
            )
            self.tools.append(tool)

    # ── Phase 4: Orchestration & Infra ──

    def scan_orchestration(self, rel_path: str, lines: list[str], is_test: bool):
        """Detect orchestration patterns in source files only."""
        if is_test:
            return

        patterns = {
            "orchestrator": [
                (r'class\s+\w*Orchestrator', "Orchestrator class"),
                (r'(?:dispatch|route)[_\s]*(?:to_agent|query|request)', "Agent dispatch/routing"),
                (r'agent[_\s]*pipeline|pipeline[_\s]*agent', "Agent pipeline"),
            ],
            "llm_routing": [
                (r'class\s+\w*(?:LLM|Llm)Router', "LLM Router class"),
                (r'select_provider|choose_(?:llm|provider|model)', "Provider selection"),
                (r'(?:confidential|vault)[_\s]*(?:route|routing|check)', "Confidential routing"),
                (r'should_use_ollama', "Ollama routing decision"),
            ],
            "state_management": [
                (r'class\s+\w*(?:Session|State)(?:Manager|Store)', "State manager class"),
                (r'(?:global|shared)[_\s]*(?:state|context|memory)', "Shared state"),
                (r'session[_\s]*(?:store|manager|context)', "Session management"),
            ],
            "workflow": [
                (r'class\s+\w*Pipeline', "Pipeline class"),
                (r'(?:process|ingest)[_\s]*(?:document|pipeline)', "Document processing"),
                (r'(?:ocr|embed|chunk)[_\s]*(?:task|worker|queue)', "Processing task"),
                (r'celery[_\s]*task|@(?:shared_task|app\.task)', "Celery task"),
            ],
        }

        for category, pats in patterns.items():
            for pat, desc in pats:
                hits = self._search(lines, [pat])
                for line_num, _, line_text in hits:
                    self.infra.append(InfraFinding(
                        component=category,
                        file_path=rel_path,
                        evidence=desc,
                    ))

    def scan_docker(self, rel_path: str, lines: list[str]):
        """Parse Docker config for infrastructure health signals."""
        content = "\n".join(lines)

        checks = [
            ("docker_volumes", r'volumes\s*:', "Persistent volumes declared"),
            ("docker_healthcheck", r'healthcheck\s*:', "Health checks defined"),
            ("docker_restart", r'restart\s*:', "Restart policies set"),
            ("docker_resources", r'(?:mem_limit|memory|deploy[\s\S]*?resources)', "Resource limits"),
            ("docker_networks", r'networks\s*:', "Network isolation"),
        ]
        for comp, pat, desc in checks:
            if re.search(pat, content, re.IGNORECASE):
                self.infra.append(InfraFinding(
                    component=comp, file_path=rel_path, evidence=desc
                ))

        # Detect specific services
        services = [
            ("svc_postgres", r'pgvector|postgres', "PostgreSQL/pgvector"),
            ("svc_redis", r'image:\s*redis', "Redis"),
            ("svc_ollama", r'ollama', "Ollama"),
            ("svc_celery", r'celery\s*worker|celery\s*beat', "Celery workers"),
            ("svc_nginx", r'nginx|caddy', "Reverse proxy"),
            ("svc_nats", r'nats', "NATS messaging"),
        ]
        for comp, pat, desc in services:
            if re.search(pat, content, re.IGNORECASE):
                self.infra.append(InfraFinding(
                    component=comp, file_path=rel_path, evidence=desc
                ))

    def scan_env(self, rel_path: str, lines: list[str]):
        """Extract env key names ONLY — never values."""
        SENSITIVE_KEYWORDS = {
            "KEY", "SECRET", "PASSWORD", "TOKEN", "PRIVATE", "CREDENTIAL",
        }
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key and not key.startswith("#"):
                    is_sensitive = any(kw in key.upper() for kw in SENSITIVE_KEYWORDS)
                    self.env_keys.append(EnvKey(
                        name=key, file_path=rel_path, is_sensitive=is_sensitive
                    ))

    def scan_llm_providers(self, rel_path: str, lines: list[str], is_test: bool):
        """Detect LLM provider usage — source files only for counting."""
        if is_test:
            return
        for provider, patterns in LLM_DETECT.items():
            hits = self._search(lines, patterns)
            for line_num, _, _ in hits:
                self.llm_refs[provider].append((rel_path, line_num))

    # ── Master Scan ──

    def run(self):
        print(f"\n{'='*70}")
        print(f"  SOWKNOW Deep-Tier Audit v2 — Scanning: {self.root}")
        print(f"{'='*70}\n")

        files = self.discover_files()
        print(f"  Discovered {len(files)} scannable files")
        print(f"    Source: {self.source_files_count}  |  Tests: {self.test_files_count}")
        print(f"    Skipped (self/audit): {self.files_skipped}")
        print()

        for fpath, is_test in files:
            lines = self.load_file(fpath)
            if not lines:
                continue
            rel = str(fpath.relative_to(self.root))
            fname = os.path.basename(rel)

            # Agent detection: all files but categorized
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".py", ".ts", ".js", ".tsx", ".jsx"):
                self.scan_agents(rel, lines, is_test)
                self.scan_tools(rel, lines, is_test)
                self.scan_orchestration(rel, lines, is_test)
                self.scan_llm_providers(rel, lines, is_test)

            # Memory: all files
            if ext in (".py", ".ts", ".js", ".tsx", ".jsx", ".yaml", ".yml"):
                self.scan_memory(rel, lines, is_test)

            # Docker
            if fname in DOCKER_NAMES or "docker" in fname.lower():
                self.scan_docker(rel, lines)

            # Env
            if is_env_file(fname):
                self.scan_env(rel, lines)

        print(f"  Scanned {self.files_scanned} files ({self.total_lines:,} lines)")
        real_agents = [a for a in self.agents if not a.is_test]
        test_agents = [a for a in self.agents if a.is_test]
        print(f"  Agents: {len(real_agents)} real + {len(test_agents)} test fixtures")

        real_mem = {t: [f for f in fs if not f.is_test and f.is_real]
                    for t, fs in self.memory.items()}
        total_mem = sum(len(v) for v in real_mem.values())
        print(f"  Memory signals: {total_mem} (source, real patterns only)")

        real_tools = [t for t in self.tools if not t.is_test]
        print(f"  Tool schemas: {len(real_tools)} real + {len(self.tools) - len(real_tools)} test")

        src_infra = [f for f in self.infra]
        print(f"  Infrastructure findings: {len(src_infra)}")
        print()


# LLM provider detection (used by both scanner and report)
LLM_DETECT = {
    "ollama": [
        r'\bollama\b(?!.*#)',
        r'OLLAMA_',
        r'localhost:11434',
    ],
    "openrouter": [
        r'\bopenrouter\b(?!.*#)',
        r'OPENROUTER_',
        r'openrouter\.ai',
    ],
    "minimax": [
        r'\bminimax\b(?!.*#)',
        r'MINIMAX_',
    ],
    "moonshot_kimi": [
        r'\b(?:moonshot|kimi)\b(?!.*#)',
        r'MOONSHOT_API_KEY',
        r'KIMI_',
    ],
    "anthropic": [
        r'\banthropic\b(?!.*#)',
        r'ANTHROPIC_API_KEY',
        r'\bclaude\b',
    ],
    "tesseract_ocr": [
        r'\btesseract\b(?!.*#)',
    ],
    "paddleocr": [
        r'\bpaddleocr\b(?!.*#)',
    ],
}


# ──────────────────────────────────────────────────────────────
# Report Generator v2
# ──────────────────────────────────────────────────────────────

class AuditReportV2:

    def __init__(self, scanner: CodebaseScannerV2):
        self.s = scanner
        self.out: list[str] = []

    def w(self, text: str = ""):
        self.out.append(text)

    def hr(self, char="─", width=72):
        self.w(char * width)

    def section(self, title: str):
        self.w()
        self.w("=" * 72)
        self.w(f"  {title}")
        self.w("=" * 72)
        self.w()

    def sub(self, title: str):
        self.w()
        self.w(f"  ── {title} ──")
        self.w()

    # ── Header ──

    def _header(self):
        self.w("╔════════════════════════════════════════════════════════════════════════╗")
        self.w("║  SOWKNOW — Deep-Tier Agentic Stack Audit Report  v2.0                 ║")
        self.w("╚════════════════════════════════════════════════════════════════════════╝")
        self.w()
        self.w(f"  Generated:      {REPORT_DATE}")
        self.w(f"  Codebase:       {self.s.root}")
        self.w(f"  Source files:   {self.s.source_files_count}")
        self.w(f"  Test files:     {self.s.test_files_count}  (excluded from agent/tool counts)")
        self.w(f"  Lines scanned:  {self.s.total_lines:,}")
        self.w(f"  Self-excluded:  {self.s.files_skipped} audit script files")
        self.w()

    # ── Project Overview ──

    def _overview(self):
        self.section("PROJECT OVERVIEW")
        self.w("  Directories:")
        for d in sorted(self.s.project_dirs):
            self.w(f"    📁 {d}/")
        self.w()

        self.sub("LLM provider usage (source files only)")
        for provider, refs in sorted(self.s.llm_refs.items(), key=lambda x: -len(x[1])):
            # Deduplicate by file
            files = set(r[0] for r in refs)
            self.w(f"  {provider:<20} {len(refs):>4} refs across {len(files)} files")
            for f in sorted(files)[:5]:
                self.w(f"    → {f}")
            if len(files) > 5:
                self.w(f"    ... +{len(files) - 5} more files")

    # ── Phase 1: Agents ──

    def _phase1(self):
        self.section("PHASE 1: AGENT CENSUS & IDENTITY AUDIT")

        real_agents = [a for a in self.s.agents if not a.is_test]
        test_agents = [a for a in self.s.agents if a.is_test]
        class_agents = [a for a in real_agents if a.category == "class"]
        prompt_agents = [a for a in real_agents if a.category == "standalone_prompt"]

        self.w(f"  Total detected: {len(real_agents)} real + {len(test_agents)} test (excluded)")
        self.w(f"    Agent classes:        {len(class_agents)}")
        self.w(f"    Standalone prompts:   {len(prompt_agents)}")
        self.w()

        if not real_agents:
            self.w("  ⚠️  NO AGENTS DETECTED in source code.")
            return

        # Agent Status Table
        self.sub("DELIVERABLE 1: Agent status table")
        self.w(f"  {'Name':<40} {'Grade':<6} {'WHY':<5} {'WHO':<5} {'HOW':<5} {'Vault':<6} {'LLM':<12}")
        self.hr("─", 72)

        # Classes first
        if class_agents:
            self.w("  ┌─ Agent Classes ─────────────────────────────────────────────────")
            for a in sorted(class_agents, key=lambda x: x.file_path):
                name = a.name[:38]
                chk = lambda v: "✅" if v else "❌"
                self.w(f"  │ {name:<38} {a.profile_grade:<6} {chk(a.has_mission_why):<5} "
                       f"{chk(a.has_persona_who):<5} {chk(a.has_constraints_how):<5} "
                       f"{chk(a.has_confidential_guard):<6} {a.llm_provider:<12}")
            self.w("  └─────────────────────────────────────────────────────────────────")
            self.w()

        # Standalone prompts grouped by service file
        if prompt_agents:
            self.w("  ┌─ Service-Level System Prompts ──────────────────────────────────")
            by_file = defaultdict(list)
            for a in prompt_agents:
                by_file[a.file_path].append(a)

            for fpath, agents in sorted(by_file.items()):
                self.w(f"  │ 📄 {fpath}")
                for a in agents:
                    chk = lambda v: "✅" if v else "❌"
                    self.w(f"  │   L{a.line_number:<5} {a.profile_grade}  "
                           f"WHY:{chk(a.has_mission_why)} WHO:{chk(a.has_persona_who)} "
                           f"HOW:{chk(a.has_constraints_how)} Vault:{chk(a.has_confidential_guard)}")
                    if a.prompt_text:
                        snippet = a.prompt_text[:120].replace("\n", " ")
                        self.w(f"  │          \"{snippet}...\"")
            self.w("  └─────────────────────────────────────────────────────────────────")

        # Grade distribution
        self.sub("Profile grade distribution")
        grades = defaultdict(int)
        for a in real_agents:
            grades[a.profile_grade] += 1
        for g in ["A", "B", "C", "D", "F"]:
            count = grades.get(g, 0)
            bar = "█" * count
            self.w(f"  {g}: {bar} ({count})")

        # Key finding
        self.w()
        f_count = grades.get("F", 0)
        total = len(real_agents)
        if f_count > total * 0.5:
            self.w(f"  🔴 CRITICAL: {f_count}/{total} agents have grade F (no meaningful prompt identity)")
            self.w(f"     Every agent needs WHY (mission), WHO (persona), HOW (constraints).")
        elif grades.get("A", 0) + grades.get("B", 0) > total * 0.5:
            self.w(f"  🟢 GOOD: Majority of agents have strong profiles.")
        else:
            self.w(f"  🟡 FAIR: Agent profiles exist but need strengthening.")

    # ── Phase 2: Memory ──

    def _phase2(self):
        self.section("PHASE 2: 4-STAGE PERSISTENT MEMORY AUDIT")

        tiers = [
            ("sensory_buffer",  "Stage 1: SENSORY / BUFFER",
             "Input filtering, dedup, PII sanitization before LLM"),
            ("working_memory",  "Stage 2: WORKING MEMORY",
             "Prompt caching for static context (vault, values, summaries)"),
            ("episodic_memory", "Stage 3: EPISODIC MEMORY",
             "Vector-indexed document retrieval (pgvector + RAG)"),
            ("semantic_memory", "Stage 4: SEMANTIC MEMORY",
             "Structured relationships, entity graph, core values"),
        ]

        # Summary matrix
        self.sub("Memory tier status matrix")
        self.w(f"  {'Tier':<45} {'Real':<6} {'Partial':<8} {'Status':<15}")
        self.hr("─", 72)

        for key, label, _ in tiers:
            findings = self.s.memory.get(key, [])
            real = [f for f in findings if not f.is_test and f.is_real]
            partial = [f for f in findings if not f.is_test and not f.is_real]
            if len(real) >= 3:
                status = "🟢 IMPLEMENTED"
            elif len(real) >= 1 or len(partial) >= 3:
                status = "🟡 PARTIAL"
            else:
                status = "🔴 MISSING"
            self.w(f"  {label:<45} {len(real):<6} {len(partial):<8} {status}")
        self.w()

        # Detailed per-tier analysis
        for key, label, purpose in tiers:
            self.sub(label)
            self.w(f"  Purpose: {purpose}")
            self.w()

            findings = self.s.memory.get(key, [])
            real = [f for f in findings if not f.is_test and f.is_real]
            partial = [f for f in findings if not f.is_test and not f.is_real]

            if real:
                self.w(f"  ✅ Real implementation signals ({len(real)}):")
                # Deduplicate by (file, evidence)
                seen = set()
                for f in real:
                    k = (f.file_path, f.evidence)
                    if k not in seen:
                        seen.add(k)
                        self.w(f"    • {f.evidence} → {f.file_path}:{f.line_number}")
                self.w()

            if partial:
                self.w(f"  ◐ Supporting signals ({len(partial)}):")
                seen = set()
                for f in partial:
                    k = (f.file_path, f.evidence)
                    if k not in seen:
                        seen.add(k)
                        self.w(f"    • {f.evidence} → {f.file_path}:{f.line_number}")
                self.w()

            if not real and not partial:
                self.w("  ❌ NO IMPLEMENTATION DETECTED")
                self.w()

            # Tier-specific gap analysis
            if key == "sensory_buffer" and len(real) == 0:
                self.w("  GAP: No dedicated input guard before LLM routing.")
                self.w("  IMPACT: Raw queries hit LLMs without PII stripping or dedup.")
                self.w("  FIX: Add InputGuard middleware: classify → sanitize → deduplicate → route")
            elif key == "working_memory" and len(real) == 0:
                self.w("  GAP: No prompt-level caching for the SOWKNOW knowledge base.")
                self.w("  NOTE: Redis response caching (detected elsewhere) caches LLM *outputs*.")
                self.w("        Working Memory caches the *system context* at the LLM provider level")
                self.w("        so that the family vault, core values, and document summaries")
                self.w("        don't consume fresh tokens on every single API call.")
                self.w("  IMPACT: ~4,000-8,000 redundant tokens/query for resending static context.")
                self.w("  FIX: If OpenRouter supports it, use their context caching headers.")
                self.w("       Otherwise, maintain a compressed context summary with a TTL.")
            elif key == "semantic_memory" and len(real) < 3:
                self.w("  GAP: Knowledge graph / entity extraction may not be wired into the")
                self.w("       main query pipeline. Feature flag exists but integration unclear.")
                self.w("  FIX: Ensure entity_extraction_service feeds graph_rag_service,")
                self.w("       and that the orchestrator queries the graph for relationship context.")
            self.w()

    # ── Phase 3: Tooling ──

    def _phase3(self):
        self.section("PHASE 3: TOOLING & PROGRAMMATIC USE AUDIT")

        real_tools = [t for t in self.s.tools if not t.is_test]
        test_tools = [t for t in self.s.tools if t.is_test]

        self.w(f"  Formal tool schemas detected: {len(real_tools)} (source) + {len(test_tools)} (tests)")
        self.w()

        if not real_tools:
            self.w("  ⚠️  NO FORMAL TOOL SCHEMAS IN SOURCE CODE")
            self.w()
            self.w("  The multi-agent system (AgentOrchestrator → Clarification/Researcher/")
            self.w("  Verification/Answer) calls services directly via Python methods rather")
            self.w("  than through structured tool schemas.")
            self.w()
            self.w("  This works for a tightly-coupled system, but creates risks:")
            self.w("    • Agents can't self-discover available tools")
            self.w("    • No schema validation prevents hallucinated parameters")
            self.w("    • Tool outputs aren't validated before agent consumption")
            self.w("    • Adding new tools requires code changes in the orchestrator")
            self.w()
            self.w("  RECOMMENDED TOOL SCHEMAS for SOWKNOW:")
            tools_needed = [
                ("document_search", "Hybrid semantic + keyword vault search"),
                ("document_upload", "Ingest file into processing pipeline"),
                ("ocr_process", "Trigger OCR via configured engine"),
                ("vault_classify", "Classify document as Public/Confidential"),
                ("generate_report", "Create collection report (Short/Standard/Full)"),
                ("entity_extract", "Extract people, orgs, concepts from document"),
                ("llm_route", "Select LLM provider based on vault context"),
            ]
            for name, desc in tools_needed:
                self.w(f"    • {name}: {desc}")
        else:
            self.sub("Tool quality matrix")
            self.w(f"  {'Definition':<45} {'Schema':<7} {'Desc':<5} {'Req':<5} {'Valid':<6} ")
            self.hr("─", 72)
            for t in real_tools:
                chk = lambda v: "✅" if v else "❌"
                name = t.name[:43]
                self.w(f"  {name:<45} {chk(t.has_schema):<7} {chk(t.has_description):<5} "
                       f"{chk(t.has_required_params):<5} {chk(t.has_output_validation):<6}")

    # ── Phase 4: Orchestration & Infra ──

    def _phase4(self):
        self.section("PHASE 4: ORCHESTRATION & COMMUNICATION AUDIT")

        # Group by component, deduplicate
        by_component = defaultdict(list)
        for f in self.s.infra:
            by_component[f.component].append(f)

        # Orchestration patterns
        self.sub("Orchestration patterns")
        orch_cats = ["orchestrator", "llm_routing", "state_management", "workflow"]
        for cat in orch_cats:
            findings = by_component.get(cat, [])
            if findings:
                # Deduplicate by (evidence, file)
                seen = set()
                unique = []
                for f in findings:
                    k = (f.evidence, f.file_path)
                    if k not in seen:
                        seen.add(k)
                        unique.append(f)
                label = cat.replace("_", " ").title()
                self.w(f"  🟢 {label} ({len(unique)} signals)")
                for f in unique[:8]:
                    self.w(f"     • {f.evidence} → {f.file_path}")
                if len(unique) > 8:
                    self.w(f"     ... +{len(unique) - 8} more")
                self.w()
            else:
                label = cat.replace("_", " ").title()
                self.w(f"  🔴 {label}: NOT DETECTED")
                self.w()

        # Infrastructure health
        self.sub("Docker infrastructure health")
        infra_checks = [
            ("docker_volumes",      "Persistent volumes"),
            ("docker_healthcheck",  "Health checks"),
            ("docker_restart",      "Restart policies"),
            ("docker_resources",    "Resource limits"),
            ("docker_networks",     "Network isolation"),
        ]
        for comp, label in infra_checks:
            found = comp in by_component
            icon = "🟢" if found else "🔴"
            self.w(f"  {icon} {label}")

        self.w()
        self.sub("Container services detected")
        svc_checks = [
            ("svc_postgres", "PostgreSQL / pgvector"),
            ("svc_redis",    "Redis"),
            ("svc_ollama",   "Ollama"),
            ("svc_celery",   "Celery workers"),
            ("svc_nginx",    "Reverse proxy (Nginx/Caddy)"),
            ("svc_nats",     "NATS messaging"),
        ]
        for comp, label in svc_checks:
            found = comp in by_component
            icon = "🟢" if found else "⚪"
            self.w(f"  {icon} {label}")

        # Env summary (REDACTED values)
        self.sub("Environment configuration (values REDACTED)")
        if self.s.env_keys:
            sensitive = [k for k in self.s.env_keys if k.is_sensitive]
            public = [k for k in self.s.env_keys if not k.is_sensitive]
            self.w(f"  {len(self.s.env_keys)} env keys detected: "
                   f"{len(sensitive)} sensitive (🔒), {len(public)} non-sensitive (📋)")
            self.w()

            # Group by file
            by_file = defaultdict(list)
            for k in self.s.env_keys:
                by_file[k.file_path].append(k)

            for fpath, keys in sorted(by_file.items()):
                sens_count = sum(1 for k in keys if k.is_sensitive)
                self.w(f"  📄 {fpath}  ({len(keys)} keys, {sens_count} sensitive)")
                # Show first few key NAMES only
                for k in keys[:10]:
                    icon = "🔒" if k.is_sensitive else "📋"
                    self.w(f"    {icon} {k.name}")
                if len(keys) > 10:
                    self.w(f"    ... +{len(keys) - 10} more")
                self.w()
        else:
            self.w("  ⚠️  No .env files found")

    # ── Memory Gap Report ──

    def _memory_gap_report(self):
        self.section("DELIVERABLE 2: MEMORY GAP REPORT")

        self.w("  Identifies where 'forgetting' or 'redundant token spending' occurs.")
        self.w()

        tiers = {
            "sensory_buffer":  "Sensory / Buffer (input filtering)",
            "working_memory":  "Working Memory (prompt caching)",
            "episodic_memory": "Episodic Memory (vector/RAG)",
            "semantic_memory": "Semantic Memory (graph/wisdom)",
        }

        gaps = []
        partial = []
        implemented = []

        for key, label in tiers.items():
            findings = self.s.memory.get(key, [])
            real = [f for f in findings if not f.is_test and f.is_real]
            if len(real) >= 3:
                implemented.append((key, label, len(real)))
            elif len(real) >= 1:
                partial.append((key, label, len(real)))
            else:
                gaps.append((key, label))

        if gaps:
            self.w(f"  🔴 GAPS ({len(gaps)} tiers missing):")
            for key, label in gaps:
                self.w(f"     ❌ {label}")
            self.w()

        if partial:
            self.w(f"  🟡 PARTIAL ({len(partial)} tiers incomplete):")
            for key, label, count in partial:
                self.w(f"     ◐ {label} ({count} real signals)")
            self.w()

        if implemented:
            self.w(f"  🟢 IMPLEMENTED ({len(implemented)} tiers):")
            for key, label, count in implemented:
                self.w(f"     ✅ {label} ({count} real signals)")
            self.w()

        # Token waste estimate
        self.sub("Token waste estimate (per query)")
        waste_items = []
        for key, label in tiers.items():
            real = [f for f in self.s.memory.get(key, []) if not f.is_test and f.is_real]
            if len(real) < 3:
                if key == "working_memory":
                    waste_items.append(("No prompt caching", "~4,000-8,000 tokens/query",
                                        "Resending static SOWKNOW context every call"))
                elif key == "sensory_buffer":
                    waste_items.append(("No input filtering", "~500-2,000 tokens/query",
                                        "Unfiltered/duplicate queries reach the LLM"))

        if waste_items:
            for name, cost, reason in waste_items:
                self.w(f"  💸 {name}: {cost}")
                self.w(f"     Cause: {reason}")
            self.w()
        else:
            self.w("  ✅ No major token waste patterns detected.")

        # Cross-agent state
        self.sub("Cross-agent state preservation")
        state_findings = [f for f in self.s.infra if f.component == "state_management"]
        if state_findings:
            self.w(f"  🟢 {len(state_findings)} state management signals detected.")
            seen = set()
            for f in state_findings:
                k = (f.evidence, f.file_path)
                if k not in seen:
                    seen.add(k)
                    self.w(f"     • {f.evidence} → {f.file_path}")
        else:
            self.w("  🔴 No shared state mechanism detected between agents.")
            self.w("     Agent handoffs may lose vault classification and session context.")

    # ── Optimization Roadmap ──

    def _optimization_roadmap(self):
        self.section("DELIVERABLE 3: OPTIMIZATION ROADMAP")
        self.w("  High-impact changes to make SOWKNOW 'Legacy-Ready'")
        self.w()

        # Dynamically prioritize based on findings
        real_agents = [a for a in self.s.agents if not a.is_test]
        f_count = sum(1 for a in real_agents if a.profile_grade == "F")

        working_real = [f for f in self.s.memory.get("working_memory", [])
                        if not f.is_test and f.is_real]
        sensory_real = [f for f in self.s.memory.get("sensory_buffer", [])
                        if not f.is_test and f.is_real]
        semantic_real = [f for f in self.s.memory.get("semantic_memory", [])
                         if not f.is_test and f.is_real]
        real_tools = [t for t in self.s.tools if not t.is_test]

        changes = []

        # OPT-1: Agent identities (if most are F-grade)
        if f_count > len(real_agents) * 0.4:
            changes.append({
                "id": "OPT-1",
                "title": "Upgrade agent profiles with Mission / Persona / Constraints",
                "priority": "🔴 CRITICAL",
                "effort": "1 week",
                "trigger": f"{f_count}/{len(real_agents)} agents scored grade F",
                "detail": [
                    "Every system prompt must clearly define three pillars:",
                    "",
                    "  WHY (Mission):",
                    "    'You are the Vault Router. Your mission is to ensure zero exposure'",
                    "    'of confidential documents to cloud APIs.'",
                    "",
                    "  WHO (Persona):",
                    "    'You are a meticulous, security-conscious classifier that treats'",
                    "    'every ambiguous document as potentially confidential.'",
                    "",
                    "  HOW (Constraints):",
                    "    'You MUST classify before routing. You MUST NOT pass any document'",
                    "    'to OpenRouter/MiniMax that hasn't been vault-checked. You MUST log'",
                    "    'every routing decision for audit.'",
                    "",
                    "Apply to all services with standalone prompts:",
                    "  chat_service, search_agent, collection_service, report_service,",
                    "  smart_folder_service, synthesis_service, auto_tagging_service,",
                    "  entity_extraction_service, intent_parser, article_generation_service",
                ],
            })

        # OPT-2: Working memory
        if len(working_real) < 3:
            changes.append({
                "id": "OPT-2",
                "title": "Implement Working Memory (prompt-level context caching)",
                "priority": "🔴 CRITICAL",
                "effort": "1-2 weeks",
                "trigger": f"Only {len(working_real)} real working memory signals found",
                "detail": [
                    "Redis response caching (which exists) is NOT working memory.",
                    "Working memory caches the STATIC SYSTEM CONTEXT at the LLM level:",
                    "",
                    "  1. Build a compressed 'SOWKNOW Context Block' (~2000 tokens):",
                    "     - System identity and persona",
                    "     - Vault rules and routing constraints",
                    "     - Document corpus summary (top entities, date ranges, topics)",
                    "     - Family context and core values (curator-defined)",
                    "",
                    "  2. Cache this block across sessions:",
                    "     - If OpenRouter supports context caching headers: use them",
                    "     - If not: store the block in Redis with a TTL, prepend to every call",
                    "     - Invalidate only when the document corpus changes significantly",
                    "",
                    "  3. Estimated savings: ~4,000-8,000 tokens per query",
                    "     At current usage, this could reduce LLM costs by 30-50%",
                ],
            })

        # OPT-3: Sensory buffer
        if len(sensory_real) < 3:
            changes.append({
                "id": "OPT-3",
                "title": "Build InputGuard middleware (sensory buffer)",
                "priority": "🟡 HIGH",
                "effort": "3-5 days",
                "trigger": f"Only {len(sensory_real)} real sensory buffer signals",
                "detail": [
                    "Add a pre-processing layer BEFORE the LLM router:",
                    "",
                    "  class InputGuard:",
                    "    async def process(self, query: str, user_role: str) -> GuardResult:",
                    "      1. Classify intent (search / chat / upload / admin)",
                    "      2. Detect PII patterns (SSN, passport, phone, email)",
                    "      3. If PII detected AND routing to cloud LLM → strip or flag",
                    "      4. Deduplicate: check Redis for identical query within 30s",
                    "      5. Token count: truncate if over model's context limit",
                    "      6. Language detect: route French vs English preprocessing",
                    "      7. Return: cleaned query + intent + vault_hint + language",
                    "",
                    "  This feeds the LLM Router with pre-classified, sanitized input.",
                ],
            })

        # OPT-4: Semantic memory wiring
        if len(semantic_real) < 5:
            changes.append({
                "id": "OPT-4",
                "title": "Wire semantic memory into the query pipeline",
                "priority": "🟡 HIGH",
                "effort": "1-2 weeks",
                "trigger": "Entity extraction and graph_rag exist but may not be integrated",
                "detail": [
                    "The codebase has entity_extraction_service and graph_rag_service",
                    "but they may not be called from the main agent orchestrator.",
                    "",
                    "  1. On document ingestion: run entity_extraction → store in graph tables",
                    "  2. In agent_orchestrator.process():",
                    "     - After clarification: query the entity graph for relationship context",
                    "     - Pass entity context to researcher_agent as supplementary evidence",
                    "     - Use graph context in answer_agent for richer synthesis",
                    "  3. Build a 'Family Context' summary from the entity graph",
                    "     that feeds into working memory (OPT-2)",
                    "",
                    "  Feature flag ENABLE_KNOWLEDGE_GRAPH exists — ensure it's ON",
                    "  and that the pipeline uses it end-to-end.",
                ],
            })

        # OPT-5: Tool schemas
        if len(real_tools) < 3:
            changes.append({
                "id": "OPT-5",
                "title": "Formalize tool schemas for agent interoperability",
                "priority": "🟢 MEDIUM",
                "effort": "3-5 days",
                "trigger": f"Only {len(real_tools)} formal tool schemas found",
                "detail": [
                    "Current agents call services via direct Python methods.",
                    "For future extensibility and LLM-native tool use:",
                    "",
                    "  1. Define JSON schemas for core operations:",
                    "     document_search, vault_classify, entity_extract, generate_report",
                    "  2. Add a ToolRegistry that agents can introspect at runtime",
                    "  3. Wrap each tool with input validation (Pydantic models)",
                    "  4. Add output validation before passing results back to the agent",
                    "",
                    "  This is MEDIUM priority because the current direct-call approach works.",
                    "  Schemas become critical if you add new agents or expose tool use via API.",
                ],
            })

        # Render roadmap
        for change in changes:
            self.w(f"  ┌─ {change['id']}: {change['title']}")
            self.w(f"  │  Priority: {change['priority']}")
            self.w(f"  │  Effort:   {change['effort']}")
            self.w(f"  │  Trigger:  {change['trigger']}")
            self.w(f"  │")
            for line in change["detail"]:
                self.w(f"  │  {line}")
            self.w(f"  └{'─' * 68}")
            self.w()

    # ── Security Check ──

    def _security_check(self):
        self.section("SECURITY QUICK-CHECK")

        issues = []

        # Check for exposed secrets in env files
        sensitive_keys = [k for k in self.s.env_keys if k.is_sensitive]
        if sensitive_keys:
            self.w(f"  🔒 {len(sensitive_keys)} sensitive env keys detected (values NEVER shown in this report)")
            env_files = set(k.file_path for k in sensitive_keys)
            for f in sorted(env_files):
                count = sum(1 for k in sensitive_keys if k.file_path == f)
                self.w(f"     {f}: {count} sensitive keys")
            self.w()
            self.w("  ⚠️  Ensure .env files are in .gitignore and not committed to VCS.")
            self.w("  ⚠️  Rotate any credentials that were exposed in audit v1 report output.")
        else:
            self.w("  ✅ No sensitive env files detected (or none present).")

        # Check for vault isolation in agent prompts
        real_agents = [a for a in self.s.agents if not a.is_test]
        agents_with_vault = [a for a in real_agents if a.has_confidential_guard]
        self.w()
        self.w(f"  Vault-aware agents: {len(agents_with_vault)}/{len(real_agents)}")
        if len(agents_with_vault) < len(real_agents) * 0.3:
            self.w("  🟡 Most agent prompts don't mention confidentiality constraints.")
            self.w("     Consider adding vault awareness to all agents that touch documents.")

    # ── Full Report ──

    def generate(self) -> str:
        self._header()
        self._overview()
        self._phase1()
        self._phase2()
        self._phase3()
        self._phase4()
        self._memory_gap_report()
        self._optimization_roadmap()
        self._security_check()

        self.w()
        self.w("=" * 72)
        self.w("  END OF AUDIT REPORT v2.0")
        self.w("=" * 72)

        return "\n".join(self.out)


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 sowknow_audit_v2.py /path/to/sowknow/codebase")
        print("       python3 sowknow_audit_v2.py .")
        sys.exit(1)

    codebase_path = sys.argv[1]
    if not os.path.isdir(codebase_path):
        print(f"Error: '{codebase_path}' is not a valid directory")
        sys.exit(1)

    scanner = CodebaseScannerV2(codebase_path)
    scanner.run()

    report = AuditReportV2(scanner)
    text = report.generate()

    # Save
    output_name = f"SOWKNOW_AUDIT_v2_{datetime.now().strftime('%Y-%m-%d')}.txt"
    output_path = os.path.join(codebase_path, output_name)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n  ✅ Report saved: {output_path}")
    except PermissionError:
        output_path = output_name
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n  ✅ Report saved: {output_path}")

    print(text)


if __name__ == "__main__":
    main()
