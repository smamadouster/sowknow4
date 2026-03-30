# Agent Learnings

> The AI updates this file whenever it makes a mistake. Before starting new tasks, the agent reads this file.

---

## Mistakes Made

### Over-reliance on local memory context in multi-step planning loops

**Description:** Over-reliance on local memory context in multi-step planning loops. Resulted in model hallucination when context limit was exceeded.

**Impact:** Deployment failed; test suite coverage dropped by 18%.

---

## Patterns to Avoid

### Global state mutation during concurrent agent operations

**Pattern:** Global state mutation during concurrent agent operations.

**Risk:** Race conditions, unpredictable outputs, trace fragmentation.

---

## Better Approaches

### Context segmentation and dynamic retrieval

**Recommendation:** Implement context segmentation and dynamic retrieval using FAISS vectors.

**Solutions:** Use structured data representations (JSON) for input/output and explicit state management with atomicity.
