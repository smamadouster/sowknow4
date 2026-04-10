#!/usr/bin/env python3
"""
SOWKNOW — Deep-Tier Agentic Stack Audit
=========================================
Principal AI Architect & Systems Engineer Audit Script

Conducts a 4-Phase audit of the SOWKNOW codebase:
  Phase 1: Agent Census & Identity Audit
  Phase 2: 4-Stage Persistent Memory Audit
  Phase 3: Tooling & Programmatic Use Audit
  Phase 4: Orchestration & Communication Audit

Deliverables:
  1. Agent Status Table
  2. Memory Gap Report
  3. Optimization Roadmap

Usage:
  python3 sowknow_audit.py /path/to/sowknow/codebase
  python3 sowknow_audit.py .   # if running from inside the codebase
"""

import os
import sys
import re
import json
import glob
import hashlib
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# ──────────────────────────────────────────────────────────────
# Configuration & Constants
# ──────────────────────────────────────────────────────────────

REPORT_VERSION = "1.0"
REPORT_DATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# File extensions to scan
CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".yaml", ".yml", ".toml", ".json", ".env", ".env.example",
    ".sh", ".bash", ".dockerfile", ".conf", ".cfg", ".ini",
}
DOCKER_FILES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
CONFIG_FILES = {".env", ".env.example", ".env.local", ".env.production", "config.py", "settings.py", "config.ts", "constants.ts"}

# Agent detection patterns — adapted for SOWKNOW's tri-LLM architecture
AGENT_PATTERNS = {
    "system_prompt": [
        r'system[_\s]*prompt\s*[=:]\s*["\']',
        r'system[_\s]*message\s*[=:]\s*["\']',
        r'SystemMessage\s*\(',
        r'role["\']?\s*:\s*["\']system["\']',
        r'SYSTEM_PROMPT\s*=',
        r'system_instruction\s*[=:]',
        r'system["\']?\s*:\s*["\']',  # OpenRouter/MiniMax format
    ],
    "agent_class": [
        r'class\s+\w*(Agent|Assistant|Bot|Orchestrator|Worker|Router|Clarifier|Researcher|Verifier|Answerer)\b',
        r'def\s+(create|build|init)_\w*(agent|assistant|bot)\b',
        r'Agent\s*\(',
        r'AgentExecutor\s*\(',
    ],
    "agent_config": [
        r'agent[_\s]*name\s*[=:]\s*["\']',
        r'agent[_\s]*role\s*[=:]\s*["\']',
        r'persona\s*[=:]\s*["\']',
        r'agent[_\s]*description\s*[=:]\s*["\']',
    ],
    "telegram_handler": [
        r'@\w+\.message_handler',
        r'@\w+\.callback_query_handler',
        r'CommandHandler\s*\(',
        r'MessageHandler\s*\(',
        r'def\s+handle_\w+',
        r'bot\.\w+_handler',
        r'application\.add_handler',
    ],
}

# Memory tier detection patterns
MEMORY_PATTERNS = {
    "sensory_buffer": {
        "patterns": [
            r'input[_\s]*filter',
            r'pre[_\s]*process',
            r'sanitize[_\s]*input',
            r'noise[_\s]*filter',
            r'buffer[_\s]*memory',
            r'input[_\s]*validation',
            r'rate[_\s]*limit',
            r'dedup(licate)?',
            r'token[_\s]*count',
            r'max[_\s]*tokens',
            r'truncat',
            r'sliding[_\s]*window',
        ],
        "description": "Sensory / Buffer Memory — Filters noise from immediate input",
    },
    "working_memory": {
        "patterns": [
            r'prompt[_\s]*cach(e|ing)',
            r'anthropic.*cache',
            r'cache[_\s]*control',
            r'ephemeral',
            r'beta.*prompt.*caching',
            r'cached[_\s]*prompt',
            r'static[_\s]*context',
            r'system[_\s]*context',
            r'context[_\s]*window',
            r'message[_\s]*history',
            r'conversation[_\s]*buffer',
            r'ConversationBufferMemory',
            r'ChatMessageHistory',
            r'openrouter.*cache',  # OpenRouter caching
        ],
        "description": "Working Memory — Prompt caching for static knowledge",
    },
    "episodic_memory": {
        "patterns": [
            r'vector[_\s]*(db|store|search|index)',
            r'pgvector',
            r'embedding',
            r'semantic[_\s]*search',
            r'similarity[_\s]*search',
            r'chroma',
            r'pinecone',
            r'weaviate',
            r'qdrant',
            r'faiss',
            r'cosine[_\s]*similarity',
            r'retrieve.*chunk',
            r'chunk.*retriev',
            r'RAG',
            r'retrieval[_\s]*augmented',
            r'multilingual.e5',  # SOWKNOW's embedding model
        ],
        "description": "Episodic Memory — Vector-indexed event/document retrieval",
    },
    "semantic_memory": {
        "patterns": [
            r'knowledge[_\s]*graph',
            r'graph[_\s]*(db|database|store)',
            r'neo4j',
            r'networkx',
            r'entity[_\s]*relation',
            r'triple[_\s]*store',
            r'ontology',
            r'relationship[_\s]*map',
            r'permanent[_\s]*memory',
            r'core[_\s]*values',
            r'family[_\s]*context',
            r'legacy[_\s]*knowledge',
            r'wisdom[_\s]*layer',
        ],
        "description": "Semantic Memory — Structured permanent relationships and core values",
    },
}

# Tool use detection patterns
TOOL_PATTERNS = {
    "tool_definition": [
        r'tools?\s*[=:]\s*\[',
        r'function[_\s]*call',
        r'tool[_\s]*choice',
        r'tool[_\s]*use',
        r'"type"\s*:\s*"function"',
        r'tool_schema',
        r'FunctionTool\s*\(',
        r'StructuredTool\s*\(',
        r'@tool\b',
        r'def\s+\w+_tool\b',
    ],
    "schema_definition": [
        r'"parameters"\s*:\s*\{',
        r'"properties"\s*:\s*\{',
        r'"required"\s*:\s*\[',
        r'"description"\s*:\s*"',
        r'json[_\s]*schema',
        r'pydantic.*BaseModel',
        r'class\s+\w+.*BaseModel',
        r'Field\s*\(',
    ],
    "output_validation": [
        r'validate[_\s]*(output|result|response|tool)',
        r'tool[_\s]*output[_\s]*valid',
        r'parse[_\s]*tool[_\s]*result',
        r'try\s*:.*tool',
        r'except.*ToolError',
        r'tool[_\s]*result[_\s]*check',
        r'output[_\s]*parser',
    ],
}

# Orchestration detection patterns
ORCHESTRATION_PATTERNS = {
    "central_orchestrator": [
        r'orchestrat(or|ion|e)',
        r'coordinator',
        r'supervisor',
        r'master[_\s]*agent',
        r'dispatch',
        r'router',
        r'planner',
    ],
    "chained_workflow": [
        r'chain\s*\(',
        r'pipeline\s*[=:\[]',
        r'SequentialChain',
        r'step[_\s]*\d+',
        r'stage[_\s]*\d+',
        r'next[_\s]*step',
        r'workflow[_\s]*step',
    ],
    "state_management": [
        r'global[_\s]*state',
        r'shared[_\s]*memory',
        r'state[_\s]*manager',
        r'context[_\s]*store',
        r'session[_\s]*state',
        r'redis',
        r'state[_\s]*machine',
        r'handoff',
    ],
    "infrastructure": [
        r'docker[_\s]*compose',
        r'volumes?\s*:',
        r'persistent[_\s]*volume',
        r'tailscale',
        r'health[_\s]*check',
        r'retry[_\s]*(logic|count|delay)',
        r'connection[_\s]*retry',
        r'exponential[_\s]*backoff',
        r'restart[_\s]*policy',
    ],
}

# LLM provider detection — adapted for SOWKNOW's tri-LLM strategy
LLM_PATTERNS = {
    "minimax": [
        r'minimax', r'MINIMAX', r'minimax[_\s]*api',
        r'MINIMAX_API_KEY', r'minimax\.chat',
        r'M2\.7', r'MiniMax',
    ],
    "openrouter": [
        r'openrouter', r'OPENROUTER', r'openrouter\.ai',
        r'OPENROUTER_API_KEY', r'mistral.*small',
    ],
    "ollama": [
        r'ollama', r'OLLAMA_', r'localhost:11434',
        r'ollama[_\s]*host', r'ollama\.chat',
        r'mistral:7b',
    ],
    "anthropic": [
        r'anthropic', r'claude', r'ANTHROPIC_API_KEY',
        r'anthropic\.Anthropic', r'claude-\d',
    ],
    "openai": [
        r'openai', r'gpt-', r'OPENAI_API_KEY',
        r'ChatOpenAI', r'openai\.chat',
    ],
    "paddleocr": [
        r'paddleocr', r'PaddleOCR', r'paddle',
        r'ocr[_\s]*engine', r'paddlepaddle',
    ],
    "tesseract": [
        r'tesseract', r'pytesseract', r'TESSERACT',
    ],
}


# ──────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────

@dataclass
class AgentProfile:
    name: str
    file_path: str
    line_number: int
    detection_method: str
    has_system_prompt: bool = False
    system_prompt_snippet: str = ""
    has_mission_why: bool = False
    has_persona_who: bool = False
    has_constraints_how: bool = False
    has_tools: bool = False
    tool_count: int = 0
    llm_provider: str = "unknown"
    reasoning_patterns: list = field(default_factory=list)
    profile_strength: str = "WEAK"  # WEAK / MODERATE / STRONG
    notes: list = field(default_factory=list)


@dataclass
class MemoryFinding:
    tier: str
    file_path: str
    line_number: int
    pattern_matched: str
    context_snippet: str
    implementation_quality: str = "UNKNOWN"  # MISSING / PARTIAL / IMPLEMENTED
    notes: str = ""


@dataclass
class ToolFinding:
    name: str
    file_path: str
    line_number: int
    has_schema: bool = False
    has_description: bool = False
    has_required_params: bool = False
    has_output_validation: bool = False
    quality: str = "UNKNOWN"  # WEAK / ADEQUATE / ROBUST


@dataclass
class InfraFinding:
    component: str
    file_path: str
    detail: str
    status: str = "UNKNOWN"  # MISSING / PARTIAL / PRESENT


# ──────────────────────────────────────────────────────────────
# Scanner Engine
# ──────────────────────────────────────────────────────────────

class CodebaseScanner:
    """Scans the SOWKNOW codebase and collects structured findings."""

    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        self.files_scanned = 0
        self.total_lines = 0
        self.file_contents: dict[str, list[str]] = {}
        self.agents: list[AgentProfile] = []
        self.memory_findings: dict[str, list[MemoryFinding]] = defaultdict(list)
        self.tool_findings: list[ToolFinding] = []
        self.infra_findings: list[InfraFinding] = []
        self.llm_usage: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.docker_config: dict = {}
        self.env_vars: dict[str, str] = {}
        self.project_structure: list[str] = []

    # ── File Discovery ──

    def discover_files(self) -> list[Path]:
        """Find all relevant files, skipping common non-project dirs."""
        skip_dirs = {
            "node_modules", ".git", "__pycache__", ".next", ".venv",
            "venv", "env", ".mypy_cache", ".pytest_cache", "dist",
            "build", ".docker", "coverage", ".turbo", ".claude",
            "docker/archived-compose",  # SOWKNOW-specific: archived compose files
        }
        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            rel_dir = os.path.relpath(dirpath, self.root)
            for fname in sorted(filenames):
                ext = os.path.splitext(fname)[1].lower()
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, self.root)
                self.project_structure.append(rel)
                if ext in CODE_EXTENSIONS or fname in DOCKER_FILES or fname in CONFIG_FILES:
                    files.append(Path(full))
        return files

    def load_file(self, path: Path) -> list[str]:
        """Load file content, returning lines."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            self.files_scanned += 1
            self.total_lines += len(lines)
            rel = str(path.relative_to(self.root))
            self.file_contents[rel] = lines
            return lines
        except Exception as e:
            return []

    # ── Pattern Matching ──

    def search_patterns(self, lines: list[str], patterns: list[str]) -> list[tuple[int, str, str]]:
        """Search lines for regex patterns. Returns [(line_num, matched_pattern, line_text)]."""
        results = []
        for i, line in enumerate(lines, 1):
            for pat in patterns:
                if re.search(pat, line, re.IGNORECASE):
                    results.append((i, pat, line.strip()))
                    break
        return results

    def get_context(self, lines: list[str], line_num: int, window: int = 3) -> str:
        """Get surrounding context lines."""
        start = max(0, line_num - 1 - window)
        end = min(len(lines), line_num + window)
        return "\n".join(l.rstrip() for l in lines[start:end])

    # ── Phase 1: Agent Census ──

    def scan_agents(self, rel_path: str, lines: list[str]):
        """Detect and profile agents in a file."""
        all_hits = []

        # Detect agent classes / definitions
        for method, patterns in AGENT_PATTERNS.items():
            hits = self.search_patterns(lines, patterns)
            for line_num, pat, line_text in hits:
                all_hits.append((line_num, method, pat, line_text))

        # Detect LLM providers used
        for provider, patterns in LLM_PATTERNS.items():
            hits = self.search_patterns(lines, patterns)
            for line_num, pat, line_text in hits:
                self.llm_usage[provider].append((rel_path, line_num))

        # Build agent profiles from class/config detections
        seen_lines = set()
        for line_num, method, pat, line_text in all_hits:
            if method in ("agent_class", "agent_config") and line_num not in seen_lines:
                seen_lines.add(line_num)
                agent = AgentProfile(
                    name=self._extract_agent_name(line_text, method),
                    file_path=rel_path,
                    line_number=line_num,
                    detection_method=method,
                )
                # Check for system prompt nearby (within 50 lines)
                nearby_start = max(0, line_num - 5)
                nearby_end = min(len(lines), line_num + 50)
                nearby_block = "\n".join(lines[nearby_start:nearby_end])

                for sp_pat in AGENT_PATTERNS["system_prompt"]:
                    if re.search(sp_pat, nearby_block, re.IGNORECASE):
                        agent.has_system_prompt = True
                        # Try to extract a snippet
                        for l in lines[nearby_start:nearby_end]:
                            if re.search(sp_pat, l, re.IGNORECASE):
                                agent.system_prompt_snippet = l.strip()[:200]
                                break
                        break

                # Evaluate profile integrity
                if agent.has_system_prompt:
                    prompt_block = nearby_block.lower()
                    agent.has_mission_why = any(w in prompt_block for w in [
                        "mission", "purpose", "goal", "objective", "your role is",
                        "you are responsible for", "your task is",
                    ])
                    agent.has_persona_who = any(w in prompt_block for w in [
                        "you are", "your name is", "persona", "identity",
                        "act as", "behave as", "your character",
                    ])
                    agent.has_constraints_how = any(w in prompt_block for w in [
                        "must not", "never", "always", "constraint", "rule",
                        "do not", "forbidden", "required to", "boundaries",
                        "limitation", "restriction",
                    ])

                # Check for tool assignments
                tool_hits = self.search_patterns(
                    lines[nearby_start:nearby_end],
                    TOOL_PATTERNS["tool_definition"]
                )
                if tool_hits:
                    agent.has_tools = True
                    agent.tool_count = len(tool_hits)

                # Detect LLM provider for this agent
                for prov, prov_patterns in LLM_PATTERNS.items():
                    if self.search_patterns(lines[nearby_start:nearby_end], prov_patterns):
                        agent.llm_provider = prov
                        break

                # Score profile strength
                score = sum([
                    agent.has_system_prompt * 2,
                    agent.has_mission_why,
                    agent.has_persona_who,
                    agent.has_constraints_how,
                    agent.has_tools,
                ])
                if score >= 5:
                    agent.profile_strength = "STRONG"
                elif score >= 3:
                    agent.profile_strength = "MODERATE"
                else:
                    agent.profile_strength = "WEAK"

                self.agents.append(agent)

        # Also detect standalone system prompts not tied to a class
        for line_num, method, pat, line_text in all_hits:
            if method == "system_prompt" and line_num not in seen_lines:
                # Check if this prompt is already covered by an agent
                covered = any(
                    abs(a.line_number - line_num) < 50 and a.file_path == rel_path
                    for a in self.agents
                )
                if not covered:
                    agent = AgentProfile(
                        name=f"Standalone Prompt @ L{line_num}",
                        file_path=rel_path,
                        line_number=line_num,
                        detection_method="system_prompt",
                        has_system_prompt=True,
                        system_prompt_snippet=line_text[:200],
                    )
                    agent.profile_strength = "WEAK"
                    agent.notes.append("Standalone system prompt without agent wrapper")
                    self.agents.append(agent)

    def _extract_agent_name(self, line: str, method: str) -> str:
        """Try to extract a meaningful agent name from the code line."""
        if method == "agent_class":
            m = re.search(r'class\s+(\w+)', line)
            if m:
                return m.group(1)
        if method == "agent_config":
            m = re.search(r'["\']([^"\']+)["\']', line)
            if m:
                return m.group(1)
        # Fallback: clean up the line
        cleaned = line.strip().split("=")[0].strip().split("(")[0].strip()
        return cleaned[:60] if cleaned else "UnnamedAgent"

    # ── Phase 2: Memory Audit ──

    def scan_memory(self, rel_path: str, lines: list[str]):
        """Detect 4-stage memory implementations."""
        for tier, config in MEMORY_PATTERNS.items():
            hits = self.search_patterns(lines, config["patterns"])
            for line_num, pat, line_text in hits:
                finding = MemoryFinding(
                    tier=tier,
                    file_path=rel_path,
                    line_number=line_num,
                    pattern_matched=pat,
                    context_snippet=line_text[:200],
                )
                self.memory_findings[tier].append(finding)

    # ── Phase 3: Tooling Audit ──

    def scan_tools(self, rel_path: str, lines: list[str]):
        """Detect tool definitions and their quality."""
        tool_def_hits = self.search_patterns(lines, TOOL_PATTERNS["tool_definition"])
        schema_hits = self.search_patterns(lines, TOOL_PATTERNS["schema_definition"])
        validation_hits = self.search_patterns(lines, TOOL_PATTERNS["output_validation"])

        schema_lines = {h[0] for h in schema_hits}
        validation_lines = {h[0] for h in validation_hits}

        for line_num, pat, line_text in tool_def_hits:
            tool = ToolFinding(
                name=line_text[:80],
                file_path=rel_path,
                line_number=line_num,
            )
            # Check if schema is nearby (within 30 lines)
            for sl in schema_lines:
                if abs(sl - line_num) < 30:
                    tool.has_schema = True
                    break

            # Check for descriptions
            nearby = "\n".join(lines[max(0, line_num-2):min(len(lines), line_num+30)])
            tool.has_description = bool(re.search(r'"description"\s*:', nearby, re.IGNORECASE))
            tool.has_required_params = bool(re.search(r'"required"\s*:', nearby, re.IGNORECASE))

            # Check for output validation
            for vl in validation_lines:
                if abs(vl - line_num) < 50:
                    tool.has_output_validation = True
                    break

            # Quality score
            score = sum([tool.has_schema, tool.has_description, tool.has_required_params, tool.has_output_validation])
            if score >= 3:
                tool.quality = "ROBUST"
            elif score >= 2:
                tool.quality = "ADEQUATE"
            else:
                tool.quality = "WEAK"

            self.tool_findings.append(tool)

    # ── Phase 4: Orchestration & Infra ──

    def scan_orchestration(self, rel_path: str, lines: list[str]):
        """Detect orchestration patterns and infrastructure config."""
        for category, patterns in ORCHESTRATION_PATTERNS.items():
            hits = self.search_patterns(lines, patterns)
            for line_num, pat, line_text in hits:
                self.infra_findings.append(InfraFinding(
                    component=category,
                    file_path=rel_path,
                    detail=line_text[:200],
                    status="PRESENT",
                ))

    def scan_docker(self, rel_path: str, lines: list[str]):
        """Parse Docker configuration for infrastructure health."""
        content = "\n".join(lines)
        fname = os.path.basename(rel_path)

        if fname.startswith("docker-compose") or fname.startswith("compose"):
            self.docker_config["compose_file"] = rel_path
            # Check for volumes
            if re.search(r'volumes\s*:', content):
                self.infra_findings.append(InfraFinding(
                    component="persistent_volumes",
                    file_path=rel_path,
                    detail="Docker volumes defined",
                    status="PRESENT",
                ))
            else:
                self.infra_findings.append(InfraFinding(
                    component="persistent_volumes",
                    file_path=rel_path,
                    detail="No persistent volumes found in compose config",
                    status="MISSING",
                ))

            # Check for health checks
            if re.search(r'healthcheck\s*:', content):
                self.infra_findings.append(InfraFinding(
                    component="health_checks",
                    file_path=rel_path,
                    detail="Health checks defined in compose",
                    status="PRESENT",
                ))
            else:
                self.infra_findings.append(InfraFinding(
                    component="health_checks",
                    file_path=rel_path,
                    detail="No health checks in compose config",
                    status="MISSING",
                ))

            # Check restart policies
            if re.search(r'restart\s*:', content):
                self.infra_findings.append(InfraFinding(
                    component="restart_policy",
                    file_path=rel_path,
                    detail="Restart policies defined",
                    status="PRESENT",
                ))

            # Check resource limits
            if re.search(r'(mem_limit|memory|deploy.*resources)', content):
                self.infra_findings.append(InfraFinding(
                    component="resource_limits",
                    file_path=rel_path,
                    detail="Resource limits configured",
                    status="PRESENT",
                ))

    def scan_env(self, rel_path: str, lines: list[str]):
        """Extract environment variable patterns (never values)."""
        for line in lines:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key = line.split("=", 1)[0].strip()
                if key:
                    self.env_vars[key] = rel_path

    # ── Master Scan ──

    def run_full_scan(self):
        """Execute the complete 4-phase audit."""
        print(f"\n{'='*70}")
        print(f"  SOWKNOW Deep-Tier Audit — Scanning: {self.root}")
        print(f"{'='*70}\n")

        files = self.discover_files()
        print(f"  Discovered {len(files)} scannable files in project tree")
        print(f"  Total files in project: {len(self.project_structure)}\n")

        for fpath in files:
            lines = self.load_file(fpath)
            if not lines:
                continue
            rel = str(fpath.relative_to(self.root))

            self.scan_agents(rel, lines)
            self.scan_memory(rel, lines)
            self.scan_tools(rel, lines)
            self.scan_orchestration(rel, lines)

            fname = os.path.basename(rel)
            if fname in DOCKER_FILES or fname.startswith("docker"):
                self.scan_docker(rel, lines)
            if fname in CONFIG_FILES or fname.endswith(".env") or fname.endswith(".env.example"):
                self.scan_env(rel, lines)

        print(f"  Scanned {self.files_scanned} files ({self.total_lines:,} lines)")
        print(f"  Found {len(self.agents)} agent definitions")
        print(f"  Found {sum(len(v) for v in self.memory_findings.values())} memory pattern matches")
        print(f"  Found {len(self.tool_findings)} tool definitions")
        print(f"  Found {len(self.infra_findings)} infrastructure findings")
        print()


# ──────────────────────────────────────────────────────────────
# Report Generator
# ──────────────────────────────────────────────────────────────

class AuditReportGenerator:
    """Generates the final structured audit report."""

    def __init__(self, scanner: CodebaseScanner):
        self.s = scanner
        self.lines: list[str] = []

    def w(self, text: str = ""):
        self.lines.append(text)

    def divider(self, char="-", width=70):
        self.w(char * width)

    def section_header(self, title: str):
        self.w()
        self.divider("=")
        self.w(f"  {title}")
        self.divider("=")
        self.w()

    def sub_header(self, title: str):
        self.w()
        self.divider("-")
        self.w(f"  {title}")
        self.divider("-")
        self.w()

    # ── Report Sections ──

    def generate_header(self):
        self.w("+======================================================================+")
        self.w("|                                                                      |")
        self.w("|   SOWKNOW -- Multi-Generational Legacy Knowledge System              |")
        self.w("|   Deep-Tier Agentic Stack Audit Report                               |")
        self.w("|                                                                      |")
        self.w("+======================================================================+")
        self.w()
        self.w(f"  Report Version:  {REPORT_VERSION}")
        self.w(f"  Generated:       {REPORT_DATE}")
        self.w(f"  Codebase Root:   {self.s.root}")
        self.w(f"  Files Scanned:   {self.s.files_scanned}")
        self.w(f"  Lines Analyzed:  {self.s.total_lines:,}")
        self.w()

    def generate_project_overview(self):
        self.section_header("PROJECT STRUCTURE OVERVIEW")
        # Show top-level directories
        top_dirs = set()
        top_files = []
        for p in self.s.project_structure:
            parts = p.split(os.sep)
            if len(parts) > 1:
                top_dirs.add(parts[0])
            else:
                top_files.append(p)

        self.w("  Top-level directories:")
        for d in sorted(top_dirs):
            self.w(f"    [DIR] {d}/")
        self.w()
        self.w("  Top-level files:")
        for f in sorted(top_files)[:20]:
            self.w(f"    [FILE] {f}")
        if len(top_files) > 20:
            self.w(f"    ... and {len(top_files) - 20} more")

    def generate_phase1(self):
        self.section_header("PHASE 1: AGENT CENSUS & IDENTITY AUDIT")

        if not self.s.agents:
            self.w("  [WARNING] NO AGENTS DETECTED in the codebase.")
            self.w()
            self.w("  This means one of the following:")
            self.w("    1. The codebase does not yet implement agentic patterns")
            self.w("    2. Agents are defined using non-standard patterns not caught by the scanner")
            self.w("    3. The codebase path provided does not contain the main application code")
            self.w()
            self.w("  RECOMMENDATION: For a Legacy-Grade system, SOWKNOW requires at minimum:")
            self.w("    - Document Ingestion Agent (OCR pipeline orchestration)")
            self.w("    - RAG Retrieval Agent (semantic search + context assembly)")
            self.w("    - Conversational Agent (chat interface, tri-LLM routing)")
            self.w("    - Confidential Router Agent (vault isolation enforcement)")
            self.w("    - Telegram Interface Agent (mobile-first interactions)")
            self.w("    - Collection/Report Agent (Smart Collections & Smart Folders)")
            self.w()
        else:
            self.sub_header("Agent Status Table")
            # Table header
            self.w(f"  {'Agent Name':<35} {'File':<30} {'Profile':<10} {'Tools':<6} {'LLM':<12}")
            self.w(f"  {'-'*35} {'-'*30} {'-'*10} {'-'*6} {'-'*12}")
            for a in self.s.agents:
                short_path = a.file_path[-28:] if len(a.file_path) > 28 else a.file_path
                name = a.name[:33] if len(a.name) > 33 else a.name
                tools = f"Y ({a.tool_count})" if a.has_tools else "N"
                self.w(f"  {name:<35} {short_path:<30} {a.profile_strength:<10} {tools:<6} {a.llm_provider:<12}")
            self.w()

            self.sub_header("Profile Integrity Breakdown")
            for a in self.s.agents:
                icon = {"STRONG": "[OK]", "MODERATE": "[WARN]", "WEAK": "[FAIL]"}[a.profile_strength]
                self.w(f"  {icon} {a.name} ({a.file_path}:{a.line_number})")
                self.w(f"     System Prompt:     {'YES' if a.has_system_prompt else 'MISSING'}")
                self.w(f"     Mission (Why):     {'YES' if a.has_mission_why else 'MISSING'}")
                self.w(f"     Persona (Who):     {'YES' if a.has_persona_who else 'MISSING'}")
                self.w(f"     Constraints (How): {'YES' if a.has_constraints_how else 'MISSING'}")
                self.w(f"     Tool-Ready:        {'YES' if a.has_tools else 'No tools attached'}")
                if a.system_prompt_snippet:
                    self.w(f"     Prompt Excerpt:    {a.system_prompt_snippet[:120]}...")
                if a.notes:
                    for note in a.notes:
                        self.w(f"     Note: {note}")
                self.w()

        # LLM Usage Summary
        self.sub_header("LLM Provider Detection")
        for provider, hits in sorted(self.s.llm_usage.items()):
            self.w(f"  {provider}: {len(hits)} references")
            for path, line in hits[:5]:
                self.w(f"    -> {path}:{line}")
            if len(hits) > 5:
                self.w(f"    ... and {len(hits) - 5} more")
        if not self.s.llm_usage:
            self.w("  [WARNING] No LLM provider references detected")

    def generate_phase2(self):
        self.section_header("PHASE 2: 4-STAGE PERSISTENT MEMORY AUDIT")

        tier_labels = {
            "sensory_buffer": ("Stage 1", "SENSORY / BUFFER MEMORY"),
            "working_memory": ("Stage 2", "WORKING MEMORY (Prompt Caching)"),
            "episodic_memory": ("Stage 3", "EPISODIC MEMORY (Event-Based / Vector)"),
            "semantic_memory": ("Stage 4", "SEMANTIC MEMORY (Wisdom-Based / Graph)"),
        }

        # Summary matrix
        self.sub_header("Memory Tier Status Matrix")
        self.w(f"  {'Tier':<50} {'Signals':<10} {'Status':<15}")
        self.w(f"  {'-'*50} {'-'*10} {'-'*15}")
        for tier_key, (stage, label) in tier_labels.items():
            findings = self.s.memory_findings.get(tier_key, [])
            count = len(findings)
            if count == 0:
                status = "[MISSING]"
            elif count <= 2:
                status = "[PARTIAL]"
            else:
                status = "[DETECTED]"
            self.w(f"  {stage}: {label:<43} {count:<10} {status:<15}")
        self.w()

        # Detailed findings per tier
        for tier_key, (stage, label) in tier_labels.items():
            self.sub_header(f"{stage}: {label}")
            findings = self.s.memory_findings.get(tier_key, [])
            desc = MEMORY_PATTERNS[tier_key]["description"]
            self.w(f"  Purpose: {desc}")
            self.w()

            if not findings:
                self.w(f"  [WARNING] NO IMPLEMENTATION DETECTED")
                self.w()
                # Tier-specific recommendations
                if tier_key == "sensory_buffer":
                    self.w("  GAP: No input filtering or noise reduction layer found.")
                    self.w("  IMPACT: Raw user queries hit the LLM without deduplication,")
                    self.w("    token counting, or input sanitization. This wastes tokens")
                    self.w("    and increases hallucination risk.")
                    self.w("  FIX: Implement a pre-processing middleware that:")
                    self.w("    - Deduplicates repeated queries within a session")
                    self.w("    - Enforces token limits before LLM calls")
                    self.w("    - Sanitizes PII from queries routed to cloud LLMs")
                    self.w("    - Classifies intent to route Confidential vs Public queries")
                elif tier_key == "working_memory":
                    self.w("  GAP: No prompt caching detected.")
                    self.w("  IMPACT: The SOWKNOW core knowledge base (family vault,")
                    self.w("    core values, historical document summaries) is resent")
                    self.w("    as full tokens on every API call. This is a CRITICAL")
                    self.w("    cost and latency penalty for a Legacy Vault system.")
                    self.w("  FIX: Implement prompt caching with cache_control")
                    self.w("    for all static context blocks. OpenRouter supports")
                    self.w("    response caching which is already in SOWKNOW's design.")
                elif tier_key == "episodic_memory":
                    self.w("  GAP: No vector database or semantic retrieval detected.")
                    self.w("  IMPACT: The RAG pipeline cannot function without vector storage.")
                    self.w("    Documents cannot be semantically searched.")
                    self.w("  FIX: Implement pgvector with:")
                    self.w("    - multilingual-e5-large embeddings (1024 dims)")
                    self.w("    - Hybrid retrieval: cosine similarity + full-text search")
                    self.w("    - Heritage-aware retrieval weighting (temporal + relational)")
                elif tier_key == "semantic_memory":
                    self.w("  GAP: No knowledge graph or structured relationship store.")
                    self.w("  IMPACT: SOWKNOW cannot preserve permanent relationships,")
                    self.w("    family connections, core values, or conceptual mappings.")
                    self.w("    Without it, the system is just a document search engine.")
                    self.w("  FIX: Implement a structured relationship layer:")
                    self.w("    - Entity extraction on ingestion (people, orgs, concepts)")
                    self.w("    - Relationship graph (SQL or graph DB)")
                    self.w("    - Core values registry (curator-defined permanent truths)")
                    self.w("    - Timeline construction for temporal reasoning")
            else:
                self.w(f"  Found {len(findings)} signal(s):")
                self.w()
                for f in findings[:10]:
                    self.w(f"    >> {f.file_path}:{f.line_number}")
                    self.w(f"       Pattern: {f.pattern_matched}")
                    self.w(f"       Context: {f.context_snippet[:150]}")
                    self.w()
                if len(findings) > 10:
                    self.w(f"    ... and {len(findings) - 10} more signals")
            self.w()

    def generate_phase3(self):
        self.section_header("PHASE 3: TOOLING & PROGRAMMATIC USE AUDIT")

        if not self.s.tool_findings:
            self.w("  [WARNING] NO TOOL DEFINITIONS DETECTED")
            self.w()
            self.w("  For SOWKNOW's agentic architecture, the following tools are required:")
            self.w("    - document_search -- Hybrid semantic + keyword search")
            self.w("    - document_upload -- Ingest files into the processing pipeline")
            self.w("    - ocr_process -- Trigger PaddleOCR with Tesseract fallback")
            self.w("    - generate_report -- Create Smart Collection reports")
            self.w("    - vault_classify -- Route documents to Public/Confidential buckets")
            self.w("    - llm_route -- Switch between MiniMax/OpenRouter/Ollama based on context")
            self.w("    - entity_extract -- Pull people, orgs, concepts from documents")
            self.w("    - telegram_notify -- Send notifications via Telegram bot")
        else:
            self.sub_header("Tool Quality Matrix")
            self.w(f"  {'Tool Definition':<50} {'Schema':<8} {'Desc':<6} {'Req':<6} {'Valid':<6} {'Quality':<8}")
            self.w(f"  {'-'*50} {'-'*8} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")
            for t in self.s.tool_findings:
                name = t.name[:48]
                schema = "Y" if t.has_schema else "N"
                desc = "Y" if t.has_description else "N"
                req = "Y" if t.has_required_params else "N"
                valid = "Y" if t.has_output_validation else "N"
                self.w(f"  {name:<50} {schema:<8} {desc:<6} {req:<6} {valid:<6} {t.quality:<8}")
            self.w()

            # Schema rigor assessment
            robust = sum(1 for t in self.s.tool_findings if t.quality == "ROBUST")
            adequate = sum(1 for t in self.s.tool_findings if t.quality == "ADEQUATE")
            weak = sum(1 for t in self.s.tool_findings if t.quality == "WEAK")
            self.w(f"  Schema Rigor Summary: {robust} Robust / {adequate} Adequate / {weak} Weak")
            if weak > 0:
                self.w(f"  [WARNING] {weak} tool(s) lack proper schema definitions -- high risk of hallucinated calls")

    def generate_phase4(self):
        self.section_header("PHASE 4: ORCHESTRATION & COMMUNICATION AUDIT")

        # Categorize findings
        categories = defaultdict(list)
        for f in self.s.infra_findings:
            categories[f.component].append(f)

        if not self.s.infra_findings:
            self.w("  [WARNING] NO ORCHESTRATION PATTERNS DETECTED")
            self.w()
            self.w("  SOWKNOW requires a Central Orchestrator pattern for Legacy Vault operations:")
            self.w("    - A Routing Agent that classifies queries and dispatches to specialists")
            self.w("    - Chained workflows for document ingestion (Upload -> OCR -> Chunk -> Embed -> Index)")
            self.w("    - Global state management for cross-agent context preservation")
            self.w("    - Confidential/Public routing as a first-class orchestration concern")
        else:
            for cat, findings in sorted(categories.items()):
                self.sub_header(f"Component: {cat.replace('_', ' ').title()}")
                for f in findings:
                    status_icon = {"PRESENT": "[OK]", "PARTIAL": "[WARN]", "MISSING": "[FAIL]"}[f.status]
                    self.w(f"  {status_icon} {f.detail}")
                    self.w(f"     File: {f.file_path}")
                self.w()

        # Docker / Infrastructure summary
        self.sub_header("Infrastructure Health Check")
        infra_items = {
            "Docker Compose": any(f.component == "persistent_volumes" for f in self.s.infra_findings),
            "Persistent Volumes": any(f.component == "persistent_volumes" and f.status == "PRESENT" for f in self.s.infra_findings),
            "Health Checks": any(f.component == "health_checks" and f.status == "PRESENT" for f in self.s.infra_findings),
            "Restart Policies": any(f.component == "restart_policy" and f.status == "PRESENT" for f in self.s.infra_findings),
            "Resource Limits": any(f.component == "resource_limits" and f.status == "PRESENT" for f in self.s.infra_findings),
            "Connection Retry Logic": any("retry" in f.detail.lower() for f in self.s.infra_findings),
            "Tailscale VPN": any("tailscale" in f.detail.lower() for f in self.s.infra_findings),
        }
        for item, present in infra_items.items():
            icon = "[OK]" if present else "[FAIL]"
            self.w(f"  {icon} {item}")

        # Environment variables summary
        self.sub_header("Environment Configuration")
        if self.s.env_vars:
            sensitive_prefixes = ["API_KEY", "SECRET", "PASSWORD", "TOKEN", "PRIVATE"]
            self.w(f"  {len(self.s.env_vars)} environment variables detected:")
            for key, path in sorted(self.s.env_vars.items()):
                is_sensitive = any(sp in key.upper() for sp in sensitive_prefixes)
                icon = "[SENSITIVE]" if is_sensitive else "[CONFIG]"
                self.w(f"    {icon} {key} (in {path})")
        else:
            self.w("  [WARNING] No .env files found -- check secrets management")

    def generate_memory_gap_report(self):
        self.section_header("DELIVERABLE 2: MEMORY GAP REPORT")

        self.w("  This report identifies where 'forgetting' or 'redundant token spending'")
        self.w("  occurs in the current architecture.")
        self.w()

        gaps = []

        # Check each memory tier
        for tier_key, findings in [
            ("sensory_buffer", self.s.memory_findings.get("sensory_buffer", [])),
            ("working_memory", self.s.memory_findings.get("working_memory", [])),
            ("episodic_memory", self.s.memory_findings.get("episodic_memory", [])),
            ("semantic_memory", self.s.memory_findings.get("semantic_memory", [])),
        ]:
            if not findings:
                gaps.append(tier_key)

        if len(gaps) == 4:
            self.w("  CRITICAL: ALL 4 MEMORY TIERS ARE MISSING OR UNDETECTED")
            self.w()
            self.w("  The codebase shows no evidence of a structured persistent memory model.")
            self.w("  Without this foundation, SOWKNOW operates as a stateless document store")
            self.w("  rather than a Legacy Knowledge System.")
            self.w()
            self.w("  Token Waste Estimate (per session):")
            self.w("    - Without prompt caching: ~4,000-8,000 redundant tokens per query")
            self.w("      for resending system context and knowledge base summaries")
            self.w("    - Without sensory filtering: ~500-2,000 wasted tokens per query")
            self.w("      from unfiltered/duplicate inputs")
            self.w("    - Without episodic memory: Full re-retrieval on every session restart")
            self.w("    - Without semantic memory: No persistent wisdom accumulation")
        else:
            self.w(f"  {len(gaps)} of 4 memory tiers have gaps:")
            for g in gaps:
                label = MEMORY_PATTERNS[g]["description"]
                self.w(f"    [MISSING] {label}")
            self.w()
            present = [t for t in ["sensory_buffer", "working_memory", "episodic_memory", "semantic_memory"] if t not in gaps]
            if present:
                self.w(f"  {len(present)} of 4 memory tiers show implementation signals:")
                for p in present:
                    label = MEMORY_PATTERNS[p]["description"]
                    count = len(self.s.memory_findings[p])
                    self.w(f"    [OK] {label} ({count} signals)")
        self.w()

        # Cross-agent state analysis
        self.sub_header("Cross-Agent State Preservation")
        state_findings = [f for f in self.s.infra_findings if f.component == "state_management"]
        if state_findings:
            self.w("  Global/shared state mechanisms detected:")
            for f in state_findings:
                self.w(f"    - {f.detail} ({f.file_path})")
        else:
            self.w("  [WARNING] No global state or shared memory layer detected.")
            self.w("  IMPACT: Agent handoffs will lose context. The Confidential Router")
            self.w("    cannot pass vault classification to downstream agents without")
            self.w("    a shared state mechanism.")
            self.w("  FIX: Implement a lightweight state store (Redis or PostgreSQL-backed)")
            self.w("    that carries session context, vault classification, and active")
            self.w("    document references across agent boundaries.")

    def generate_optimization_roadmap(self):
        self.section_header("DELIVERABLE 3: OPTIMIZATION ROADMAP")

        self.w("  High-Impact Architectural Changes to Make SOWKNOW 'Legacy-Ready'")
        self.w()

        changes = [
            {
                "id": "OPT-1",
                "title": "Implement 4-Stage Persistent Memory Architecture",
                "priority": "CRITICAL",
                "effort": "2-3 weeks",
                "impact": "Foundation for all intelligent features",
                "detail": [
                    "Stage 1 (Sensory): Add InputGuard middleware that classifies, deduplicates,",
                    "  and sanitizes all incoming queries before LLM routing.",
                    "Stage 2 (Working): Implement prompt caching for the SOWKNOW core knowledge",
                    "  base. OpenRouter already supports response caching -- leverage it.",
                    "  Maintain a compressed context summary prepended to every session.",
                    "Stage 3 (Episodic): Complete the pgvector RAG pipeline as specified in the PRD.",
                    "  Add heritage-aware retrieval weighting (temporal proximity, family relevance).",
                    "Stage 4 (Semantic): Build an entity-relationship layer in PostgreSQL that stores",
                    "  extracted entities, family connections, and curator-defined core values.",
                ],
            },
            {
                "id": "OPT-2",
                "title": "Define Explicit Agent Identities with Mission/Persona/Constraints",
                "priority": "HIGH",
                "effort": "1 week",
                "detail": [
                    "Every agent MUST have a system prompt that clearly defines:",
                    "  WHY: 'You are the Vault Router. Your mission is to ensure zero exposure",
                    "        of confidential documents to cloud APIs.'",
                    "  WHO: 'You are a meticulous security-conscious classifier that treats",
                    "        every ambiguous document as potentially confidential.'",
                    "  HOW: 'You MUST classify before routing. You MUST NOT pass any document",
                    "        to MiniMax/OpenRouter that hasn't been vault-checked. You MUST log",
                    "        every routing decision for audit.'",
                    "",
                    "Minimum agent roster for SOWKNOW:",
                    "  - IngestAgent -- Manages the Upload -> OCR -> Chunk -> Embed pipeline",
                    "  - VaultRouter -- Classifies Public/Confidential, enforces isolation",
                    "  - RAGRetriever -- Semantic search + heritage-aware retrieval",
                    "  - ConversationAgent -- Chat interface with multi-turn context",
                    "  - CollectionAgent -- Smart Collections & Smart Folders generation",
                    "  - TelegramAgent -- Mobile interface with upload + query support",
                ],
            },
            {
                "id": "OPT-3",
                "title": "Build a Central Orchestrator with Global State",
                "priority": "HIGH",
                "effort": "1-2 weeks",
                "detail": [
                    "Implement a Central Orchestrator (Router pattern) that:",
                    "  - Receives all user requests (web, Telegram, API)",
                    "  - Classifies intent (search, upload, chat, report, admin)",
                    "  - Routes to the appropriate specialist agent",
                    "  - Maintains a GlobalState object passed between agents:",
                    "    {",
                    '      "session_id": "...",',
                    '      "user_role": "admin|super_user|user",',
                    '      "vault_context": "public|confidential|mixed",',
                    '      "active_documents": [...],',
                    '      "conversation_history": [...],',
                    '      "memory_stage_refs": { "episodic": [...], "semantic": [...] }',
                    "    }",
                    "  - Logs all routing decisions for anomaly detection",
                ],
            },
            {
                "id": "OPT-4",
                "title": "Implement Tool Schemas with Output Validation",
                "priority": "HIGH",
                "effort": "1 week",
                "detail": [
                    "Every tool exposed to agents must have:",
                    "  - JSON Schema with precise parameter descriptions",
                    "  - Required vs optional parameter marking",
                    "  - Return type schema for output validation",
                    "  - Error handling that returns structured error objects",
                    "  - A validation layer that checks tool output before passing to the agent",
                    "",
                    "Example for the document_search tool:",
                    "  {",
                    '    "name": "document_search",',
                    '    "description": "Search the SOWKNOW vault using hybrid semantic + keyword matching.",',
                    '    "parameters": {',
                    '      "query": { "type": "string", "description": "Natural language search query", "required": true },',
                    '      "bucket": { "type": "string", "enum": ["public", "confidential", "all"], "default": "public" },',
                    '      "limit": { "type": "integer", "default": 10, "max": 100 }',
                    "    }",
                    "  }",
                ],
            },
            {
                "id": "OPT-5",
                "title": "Harden Docker Infrastructure for Legacy-Grade Persistence",
                "priority": "MEDIUM",
                "effort": "3-5 days",
                "detail": [
                    "Ensure all 4 memory stages survive container restarts:",
                    "  - Named volumes for PostgreSQL (pgvector) data",
                    "  - Named volumes for document storage (Public + Confidential buckets)",
                    "  - Health checks on ALL HTTP services (mandatory /health endpoint)",
                    "  - Restart policies: 'unless-stopped' for all services",
                    "  - Resource limits per CLAUDE.md constraints (6.4GB total)",
                    "  - Connection retry logic with exponential backoff for:",
                    "    - PostgreSQL connections",
                    "    - Ollama shared instance",
                    "    - MiniMax API",
                    "    - OpenRouter API",
                    "  - Automated backup schedule for the Wisdom layer (semantic memory)",
                ],
            },
        ]

        for i, change in enumerate(changes, 1):
            self.w(f"  +-- {change['id']}: {change['title']}")
            self.w(f"  |  Priority: {change['priority']}")
            self.w(f"  |  Effort:   {change.get('effort', 'TBD')}")
            if change.get("impact"):
                self.w(f"  |  Impact:   {change['impact']}")
            self.w(f"  |")
            for line in change["detail"]:
                self.w(f"  |  {line}")
            self.w(f"  +{'-'*66}")
            self.w()

    def generate_appendix(self):
        self.section_header("APPENDIX: RAW SCAN DATA")

        self.sub_header("A. All Detected Patterns by File")
        seen_files = set()
        for a in self.s.agents:
            seen_files.add(a.file_path)
        for findings in self.s.memory_findings.values():
            for f in findings:
                seen_files.add(f.file_path)
        for t in self.s.tool_findings:
            seen_files.add(t.file_path)
        for f in self.s.infra_findings:
            seen_files.add(f.file_path)

        for fpath in sorted(seen_files):
            self.w(f"  [FILE] {fpath}")
            # Agents in this file
            for a in self.s.agents:
                if a.file_path == fpath:
                    self.w(f"     [AGENT] {a.name} (L{a.line_number}) -- {a.profile_strength}")
            # Memory in this file
            for tier, findings in self.s.memory_findings.items():
                for f in findings:
                    if f.file_path == fpath:
                        self.w(f"     [MEMORY:{tier}] L{f.line_number} -- {f.pattern_matched}")
            # Tools in this file
            for t in self.s.tool_findings:
                if t.file_path == fpath:
                    self.w(f"     [TOOL] L{t.line_number} -- {t.quality}")
            # Infra in this file
            for f in self.s.infra_findings:
                if f.file_path == fpath:
                    self.w(f"     [INFRA:{f.component}] {f.status}")
            self.w()

    # ── Full Report Assembly ──

    def generate(self) -> str:
        self.generate_header()
        self.generate_project_overview()
        self.generate_phase1()
        self.generate_phase2()
        self.generate_phase3()
        self.generate_phase4()
        self.generate_memory_gap_report()
        self.generate_optimization_roadmap()
        self.generate_appendix()

        self.w()
        self.divider("=")
        self.w("  END OF AUDIT REPORT")
        self.divider("=")

        return "\n".join(self.lines)


# ──────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 sowknow_audit.py /path/to/sowknow/codebase")
        print("       python3 sowknow_audit.py .   # run from inside the codebase")
        sys.exit(1)

    codebase_path = sys.argv[1]
    if not os.path.isdir(codebase_path):
        print(f"Error: '{codebase_path}' is not a valid directory")
        sys.exit(1)

    # Run the scan
    scanner = CodebaseScanner(codebase_path)
    scanner.run_full_scan()

    # Generate the report
    generator = AuditReportGenerator(scanner)
    report = generator.generate()

    # Output to file and console
    output_path = os.path.join(codebase_path, "SOWKNOW_AUDIT_REPORT.txt")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  Report saved to: {output_path}")
    except PermissionError:
        # Fall back to current directory
        output_path = "SOWKNOW_AUDIT_REPORT.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  Report saved to: {output_path}")

    # Also print to console
    print(report)


if __name__ == "__main__":
    main()
