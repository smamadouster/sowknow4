# Agent Learnings

> The AI updates this file whenever it makes a mistake. Before starting new tasks, the agent reads this file.

---

## Mistakes Made

### Pattern-based bulk line deletion without a compile gate (2026-09-05)

**Description:** `sed -i '/ollama/Id'` was run across the repo to remove Ollama.
It deleted any line *containing* the word — including JSX component signatures
(search/page.tsx, chat/page.tsx), Python function-def lines
(collection_chat_service.py, llm_router.py), a multi-line call's condition
(guardian core.py), a dataclass field whose *comment* mentioned Ollama
(RoutingDecision.provider_name — every LLM call would have TypeError'd), an
orphaned `os.getenv(` (openrouter_service.py), and left a live import of a
deleted module (guardian infrastructure.py). The broken tree was committed
(2a4c669) and half-deployed before anything compiled it.

**Impact:** ~2 hours of repair across frontend/backend/guardian; backend and
guardian-hc crash-looped in production until d0b7973.

**Fix now in place:** `scripts/verify_tree.sh` (py_compile per file +
`tsc --noEmit` + JSON validity, `--all --imports` for pre-deploy) wired into
`.githooks/pre-commit` BEFORE map regeneration. Never bulk-delete by pattern;
enumerate with `git grep -i` and edit each occurrence in context.

---

### Over-reliance on local memory context in multi-step planning loops

**Description:** Over-reliance on local memory context in multi-step planning loops. Resulted in model hallucination when context limit was exceeded.

**Impact:** Deployment failed; test suite coverage dropped by 18%.

---

## Patterns to Avoid

### Deleting "dead code" by pattern without compile-gating the result

**Pattern:** `sed -i '/keyword/Id'`, `grep -rl | xargs rm`, or any bulk edit
whose only evidence is a string match.

**Risk:** Removes lines that merely mention the keyword (comments, signatures,
type definitions), breaking syntax and runtime imports tree-wide; silently
commits if no gate runs.

---

### Global state mutation during concurrent agent operations

**Pattern:** Global state mutation during concurrent agent operations.

**Risk:** Race conditions, unpredictable outputs, trace fragmentation.

---

## Better Approaches

### Context segmentation and dynamic retrieval

**Recommendation:** Implement context segmentation and dynamic retrieval using FAISS vectors.

**Solutions:** Use structured data representations (JSON) for input/output and explicit state management with atomicity.
