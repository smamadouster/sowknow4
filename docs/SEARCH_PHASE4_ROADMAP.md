# SOWKNOW Search — Phase 4 Strategic Roadmap

**Horizon:** Months 3–6  
**Objective:** Reach 98% relevance and p99 <200ms through dedicated search infrastructure  
**Status:** 📋 Planning / Not yet implemented

---

## Executive Summary

Phases 1–3 delivered the quick wins and accuracy foundation. Phase 4 is about **strategic infrastructure investments** that require longer lead times, dedicated resources, and careful A/B validation. The three pillars are:

1. **Meilisearch as a shadow index** — Sub-50ms typo-tolerant search out of the box
2. **Domain-specific embedding fine-tuning** — Teach the model the vault's vocabulary
3. **Learned ranking (LambdaMART)** — Replace heuristic RRF weights with a model trained on user feedback

---

## P4.1 Evaluate Meilisearch as Shadow Index

### Why Meilisearch?

| Capability | PostgreSQL/pgvector | Meilisearch |
|-----------|---------------------|-------------|
| Typo tolerance | ❌ None (we added trigram fallback) | ✅ Built-in, 1 typo per 4 chars |
| Prefix search | ⚠️ ILIKE + trigram | ✅ Native, <10ms |
| Faceting | ⚠️ Manual SQL | ✅ Automatic |
| Highlighting | ⚠️ ts_headline | ✅ Built-in, configurable |
| Relevance tuning | ⚠️ Custom RRF | ✅ Ranking rules API |
| p99 latency @ 100K docs | ~200–500ms | ~20–50ms |
| Self-hosted | ✅ Yes | ✅ Yes |

### Architecture

```
Upload Pipeline (Celery)
  ├── PostgreSQL (source of truth)
  └── Meilisearch (shadow index, dual-write)

Search API
  ├── Feature flag: search.meilisearch.read=false (default)
  │   └── Uses PostgreSQL hybrid search (current)
  └── Feature flag: search.meilisearch.read=true (A/B test)
      └── Uses Meilisearch primary, PostgreSQL fallback
```

### Implementation Plan

| Week | Task | Owner |
|------|------|-------|
| 1 | Deploy Meilisearch container in docker-compose | DevOps |
| 2 | Implement dual-write in `document_tasks.py` | Backend |
| 3 | Build `MeilisearchService` with same interface as `HybridSearchService` | Backend |
| 4 | Add feature flag `search.meilisearch.read` + routing logic | Backend |
| 5 | A/B test: 5% traffic to Meilisearch | Data/QA |
| 6–8 | Compare precision, recall, latency; decide full migration | Product |

### Decision Gate

**Go:** Meilisearch beats PostgreSQL by >20% on latency without accuracy regression  
**No-go:** Accuracy drops >5% or operational overhead is unacceptable  
**Hybrid:** Keep Meilisearch for suggestions + prefix search, PostgreSQL for deep semantic search

---

## P4.2 Domain-Specific Embedding Fine-Tuning

### Problem

`multilingual-e5-large` is a general-purpose model. It doesn't know that in the SOWKNOW vault:
- "bilan" means a financial balance sheet, not a scale
- "DOA" means Document d'Orientation d'Activité, not Dead on Arrival
- "tresorerie" is cash management, not a treasure hunt

### Approach: Contrastive Fine-Tuning

1. **Collect training data** from `search_history` + `search_feedback`:
   - Positive pairs: (query, clicked_document) where user gave thumbs_up
   - Negative pairs: (query, top_result_not_clicked) where user gave thumbs_down

2. **Build dataset** (~5K–10K pairs):
   ```python
   {
     "query": "bilan 2024",
     "positive": "Bilan financier consolidé 2024...",
     "negative": "Bilan de santé annuel..."
   }
   ```

3. **Fine-tune** with `sentence-transformers` MultipleNegativesRankingLoss:
   - Base model: `intfloat/multilingual-e5-large`
   - Epochs: 3
   - Batch size: 32
   - Learning rate: 2e-5

4. **Evaluate** on held-out test set:
   - Metric: Mean Reciprocal Rank (MRR) @ 10
   - Target: +10% relative improvement over base model

5. **Deploy** as new `embed-server` model version

### Resources

- GPU: 1× A100 or 1× RTX 4090 for ~4 hours of training
- Storage: ~2GB for model + dataset
- Inference: Same as current (CPU-compatible with e5-large)

---

## P4.3 Learned Ranking Model (LambdaMART)

### Why Replace RRF?

Current ranking uses hand-tuned weights:
```python
final_score = 0.7 * semantic + 0.3 * keyword  # or adaptive
```

A learned model can discover non-linear interactions:
- Documents with high keyword score + high cross-encoder score are usually excellent
- But documents with high semantic score alone may be off-topic
- User click-through rate varies by document type (PDF vs. bookmark)

### Feature Engineering

| Feature | Source | Type |
|---------|--------|------|
| semantic_score | pgvector cosine | float |
| keyword_score | ts_rank_cd | float |
| cross_encoder_score | rerank-server | float |
| title_match | ILIKE on title | binary |
| tag_match | tags table | binary |
| document_age_days | now() - created_at | float |
| doc_type | pdf, docx, etc. | categorical |
| user_feedback_avg | search_feedback | float |
| historical_ctr | search_history clicks | float |

### Model: LightGBM LambdaRank

```python
import lightgbm as lgb

# Training
train_data = lgb.Dataset(X, label=y, group=query_groups)
params = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "ndcg_eval_at": [5, 10],
    "learning_rate": 0.05,
    "num_leaves": 31,
    "feature_fraction": 0.8,
}
model = lgb.train(params, train_data, num_boost_round=500)
```

### Deployment

- Train weekly on accumulated feedback
- Deploy as `rank-server` microservice
- API: `POST /rank` → accepts feature vector JSON → returns score
- Replace RRF in `hybrid_search()` with model inference

### Target Metrics

- NDCG@5 improvement: +5–10% over RRF baseline
- Inference latency: <5ms p99

---

## P4.4 Dedicated Search Cluster

### Current Architecture Problem

Search queries compete with uploads, chat, and admin operations for:
- PostgreSQL connections
- embed-server CPU
- Backend event loop time

### Target Architecture

```
┌─────────────────┐      ┌──────────────────────┐
│   FastAPI App   │─────▶│  PostgreSQL Primary  │
│   (API layer)   │      │  (writes + reads)    │
└─────────────────┘      └──────────────────────┘
         │
         │               ┌──────────────────────┐
         └──────────────▶│  PostgreSQL Replica  │
                         │  (search reads only) │
                         └──────────────────────┘
         │
         │               ┌──────────────────────┐
         └──────────────▶│   Search Cluster     │
                         │  ┌──────────────┐    │
                         │  │ embed-server │    │
                         │  │ rerank-server│    │
                         │  │ rank-server  │    │
                         │  │ meilisearch  │    │
                         │  └──────────────┘    │
                         └──────────────────────┘
```

### Implementation

1. **Read replica** for search queries (PostgreSQL streaming replication)
2. **Separate nodes** for embed/rerank/rank servers
3. **Circuit breakers** between API and search cluster
4. **Connection pooling** (PgBouncer) for replica

---

## Phase 4 QA Commit Criteria

| Gate | Criteria | Measurement |
|------|----------|-------------|
| Meilisearch A/B | p99 latency <200ms, accuracy ≥95% | 2-week experiment, 500 queries/group |
| Embedding fine-tune | MRR@10 +10% vs. base | Held-out test set |
| Learned rank | NDCG@5 +5% vs. RRF | Labeled result set (200 queries) |
| Availability | Search cluster survives 1 node failure | Chaos test |
| Cost | Search infra < 2× current | Cloud billing |

---

## Resource Requirements

| Initiative | Engineering | Infrastructure | Timeline |
|------------|-------------|----------------|----------|
| Meilisearch | 2 weeks | 1 container | Month 1–2 |
| Embedding FT | 3 weeks | 1 GPU × 4h | Month 2–3 |
| Learned rank | 4 weeks | 1 CPU node | Month 3–4 |
| Search cluster | 2 weeks | 2–3 nodes | Month 4–5 |

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Meilisearch accuracy regression | High | Shadow index + A/B test before any traffic switch |
| Fine-tuned model overfits | Medium | Strong validation set + early stopping + regularization |
| Learned rank becomes opaque | Medium | SHAP values for feature importance + human review |
| Search cluster cost overrun | Medium | Start with read replica only; add nodes incrementally |
| Feedback data too sparse | Medium | Seed with synthetic relevance judgments from experts |

---

## Recommended Sequencing

```
Month 1:  Meilisearch deployment + dual-write + shadow validation
Month 2:  Meilisearch A/B test + decision gate
Month 3:  Embedding fine-tuning pipeline + first model
Month 4:  Learned rank training + shadow scoring
Month 5:  Learned rank A/B test + search cluster migration
Month 6:  Full Phase 4 QA commit + retrospective
```

---

*Phase 4 is approved for planning. Do not begin implementation until Phase 3 QA commit is signed off.*
