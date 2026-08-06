# LLM / ML Model Census — SOWKNOW4

Date: 2026-08-05
Scope: LLM and adjacent ML models used across the app, and which module uses what.

## Provider stack (live config)

All traffic routes through **OpenRouter** (`app/services/llm_router.py` — every
`fallback_chains` entry is `["openrouter"]`). Tiered model selection, overridable via env:

| Tier | Default model (env var) | Used for |
|------|--------------------------|----------|
| simple | `deepseek/deepseek-v4-flash-0731` (`OPENROUTER_TIER_SIMPLE`) | classification, tagging, intent, JSON parsing |
| standard | `deepseek/deepseek-v4-flash-0731` (`OPENROUTER_TIER_STANDARD`) | chat, synthesis, articles |
| complex | `deepseek/deepseek-v4-pro` (`OPENROUTER_TIER_COMPLEX`) | reports, reasoning, verification |

Model-level fallback per tier (env vars `OPENROUTER_TIER_FALLBACK_{SIMPLE,STANDARD,COMPLEX}`):
`qwen/qwen3.8-max` — tried once inside `openrouter_service` when the primary tier
model fails with 400/404 (invalid model), 429 (rate limit), or 5xx.

Fallback model (`OPENROUTER_MODEL`): `deepseek/deepseek-v4-flash-0731`.

Optional / legacy providers (not in any active chain):
- **MiniMax** `MiniMax-M2.7` (`app/services/minimax_service.py`) — used only if `MINIMAX_API_KEY` set; preferred by `llm_gateway.chat_completion_non_stream`.
- **Kimi** `moonshot-v1-128k` (`kimi_service.py`) — legacy, imported by `_build_router` but excluded from chains.
- **Ollama** `llama3.1:8b` (`ollama_service.py`) — legacy, excluded (CPU too slow); `collection_chat_service._chat_with_ollama` is dead code.
- **Together** `meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo` (`together_service.py`) — legacy, not imported by `_build_router`.

## Routing core

- `app/services/llm_gateway.py` — `LLMGateway` facade, single entry point. Default tier `standard`; task-aware override via `_TASK_TIER_MAP` (knowledge_graph→simple, chat→standard, collections→complex, smart_folders→standard). Enforces per-module semaphores, per-user concurrency, quota/cost budgets, prompt ceiling, semantic cache. Non-streaming via `chat_completion_non_stream` (MiniMax if configured, else OpenRouter).
- `app/services/llm_router.py` — `LLMRouter.generate_completion` (tries OpenRouter, then MiniMax if configured; tier fallback to simple on standard/complex failure) and `generate_report_completion` (complex → standard → bullet-point summary).

## Module census

| Module | File | Entry point | Tier → model |
|---|---|---|---|
| Chat (conversational RAG) | `app/services/chat_service.py` | gateway, `module="chat"` | standard → gemini-2.5-flash |
| Collection chat | `app/services/collection_chat_service.py` | gateway (`has_confidential` → metadata-only strip) | standard |
| Search agent (agentic SSE) | `app/services/search_agent.py` | `llm_router.generate_completion` | standard (intent fast-path skips LLM for simple queries) |
| Intent parser | `app/services/intent_parser.py` | gateway | simple |
| Smart folder — planner | `smart_folder/agent/planner.py`, `smart_folder/query_parser.py` | `llm_router.generate_completion` | simple |
| Smart folder — synthesizer | `smart_folder/agent/synthesizer.py` | `llm_router.generate_completion` | complex |
| Smart folder — report | `smart_folder/report_generator.py`, `smart_folder_service.py` | `generate_report_completion` / gateway | complex (→standard fallback); plus simple/standard calls |
| Collections (legacy) | `app/services/collection_service.py` | gateway non-stream + stream | MiniMax else standard |
| Collection orchestrator | `collection_orchestrator/result_processor.py` (simple), `summary_generator.py` (standard) | `llm_router.generate_completion` | simple / standard — analysis, extraction, grounding are **LLM-free** (compute-first) |
| Reports | `app/services/report_service.py` | `generate_report_completion` | complex → standard → bullet summary |
| Synthesis | `app/services/synthesis_service.py` | gateway | complex |
| Article generation | `app/services/article_generation_service.py` | gateway | standard |
| Progressive revelation | `app/services/progressive_revelation_service.py` | gateway | standard |
| Graph RAG | `app/services/graph_rag_service.py` | gateway | standard |
| Entity extraction | `app/services/entity_extraction_service.py` | gateway, `module="knowledge_graph"` | cascade simple → standard → complex |
| Auto-tagging | `app/services/auto_tagging_service.py` | gateway | simple |
| Deferred queries | `app/services/deferred_query_service.py` | gateway | standard (confidential-stripped) |
| Agent memory — L1 atoms / L3 profile | `app/services/memory_service.py` | gateway non-stream | MiniMax else standard |
| Learned skills | `app/services/skill_extraction_service.py` | gateway non-stream | standard |
| Legacy agents (answer/research/verify) | `app/services/agents/*.py` | gateway | standard (not wired into any router/task — dead) |
| Clarification agent | `app/services/agents/clarification_agent.py` | gateway | simple (dead) |
| Silent agent loop | `app/services/silent_agent_loop.py` | `openrouter_service` direct | complex (unreferenced elsewhere) |
| Status / health | `app/api/status.py` | `llm_gateway.get_usage_stats` | n/a (no generation) |

Notes:
- Every tier listed is the *requested* tier. Actual model may downgrade on cost-anomaly, OpenRouter model failover (400/404/429/5xx → tier fallback model `qwen/qwen3.8-max`), or full graceful fallback (bullet summary).
- Sentinel convention: providers may append `\n__USAGE__: {...}` — consumers must match `"__USAGE__" in chunk`, never `startswith`.

## Non-LLM ML models (adjacent)

| Model | Service | Role |
|---|---|---|
| `intfloat/multilingual-e5-large` | embed-server + embed-server-2 (`embed_client.py`, `embedding_service*.py`) | search embeddings |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | rerank-server (`rerank_service.py`, `RERANK_MODEL` in compose) | cross-encoder reranking |
| faster-whisper `small` | `whisper_service.py` (`WHISPER_MODEL_SIZE`) | voice-note transcription |
| PaddleOCR | `ocr_service.py` | document OCR |
