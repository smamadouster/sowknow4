# Smart Folder v2 — Enhancement Brainstorm

> **Context:** The test query *"me faire un mémo sur Ousmane Sow"* returned a thin, 2-sentence summary despite 334 document chunks and 4 entity records existing for this person in the vault.
>
> **Goal:** Identify architectural and tactical improvements to transform Smart Folder from a "entity-tag → shallow report" generator into a true **vault intelligence** system that produces deep, insightful, well-sourced reports.

---

## 1. Why the Result is Poor (Root Cause Analysis)

### 1.1 Retrieval is Entity-Mention-Centric (Blind to 80% of Content)

The current `RetrievalService` prioritizes `EntityMention` records (Signal 1). These are **extracted entities** from the NLP pipeline. But entity extraction is lossy:

- Ousmane Sow may be mentioned in 1,000+ chunks but only **tagged in 334**.
- Missed mentions: "M. Sow", "le directeur", "notre interlocuteur", "le représentant".
- The hybrid search (Signal 2) runs second with a **weak query**: `"me faire un mémo sur Ousmane Sow Ousmane Sow"` — French function words (*mémo, sur, faire, un*) pollute the semantic vector, degrading recall.

**Result:** The LLM sees ~5-10 chunks instead of 50-100 relevant passages.

### 1.2 Skills are Document-Blind

The `general_narrative` skill calls:
1. `retrieval_service.retrieve()` → gets chunk snippets
2. `analysis_service.analyze()` → queries `milestones` and `pattern_insights` tables (likely **empty** for most entities)
3. `report_generator.generate()` → feeds chunk snippets to LLM

**The skill NEVER reads full documents.** It sees:
```
"...Ousmane Sow, Directeur exécutif..." [chunk 3 of 12]
"...Monsieur Sow a signé..." [chunk 7 of 12]
```
But not the full letter, contract, or financial statement. The LLM cannot infer context, relationships, or chronology from disjointed snippets.

### 1.3 No Cross-Document Synthesis

The pipeline treats each chunk as an isolated fact. It cannot:
- Connect: "Ousmane Sow = Directeur de Matenergy" + "Matenergy a signé contrat X" → "Ousmane Sow impliqué dans contrat X"
- Track chronology across documents: promotion from "Représentant" → "Directeur" → "Directeur Exécutif"
- Detect contradictions: Document A says "Sow démissionne" while Document B says "Sow promu"

### 1.4 Analysis Layer is a No-Op

`analysis_service.analyze()` queries dedicated `milestone` and `pattern_insight` tables. But:
- These tables are **sparsely populated** ( populated by batch pipelines, not on-demand)
- For Ousmane Sow: `milestones` = 0, `pattern_insights` = 0
- The analysis returns empty arrays → report has no timeline, patterns, or trends

### 1.5 Report Generator is Under-Prompted

The LLM prompt asks for:
- title, summary, timeline[], patterns[], trends[], issues[], learnings[], recommendations[]

But with **0 milestones, 0 patterns, and 5 chunks**, the LLM has nothing to work with. It invents generic filler:
> "Ousmane Sow exerce plusieurs fonctions de direction..."

There is **no evidence depth**, no quoted passages, no document-type awareness.

---

## 2. Strategic Vision: Search-First Architecture

> **Core Insight:** The main search module (`/search`) is significantly more powerful than Smart Folder's custom retrieval. It does semantic + keyword + reranking across ALL chunks, not just entity-tagged ones. Smart Folder should **build on top of search**, not replace it.

### Proposed New Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: DEEP SEARCH (leverage the main search module)                 │
│  ├── semantic_search("Ousmane Sow", limit=50)                           │
│  ├── semantic_search("Ousmane Sow Matenergy directeur", limit=30)       │
│  ├── keyword_search("Sow" OR "Ousmane" OR "M. Sow", limit=50)           │
│  └── hybrid_search("Ousmane Sow", limit=50, rerank=true)                │
│                                                                         │
│  → Deduplicate, score-rank, cluster by document type & date             │
│  → Yield: 50-100 highly relevant chunks from 20-40 documents            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: DOCUMENT SELECTION & FULL READING                             │
│  ├── Select top-20 unique documents by relevance score                  │
│  ├── Read FULL text of each document (not just chunks)                  │
│  │   └── asset_reader tool: extract text, tables, metadata              │
│  └── Build document inventory: type, date, sender, recipient, orgs      │
│                                                                         │
│  → Yield: Full context of 20 most important documents                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PHASE 3: STRUCTURED EXTRACTION (per-document)                          │
│  ├── Extract: people, organizations, roles, dates, amounts, locations   │
│  ├── Extract: key events, decisions, commitments, obligations           │
│  ├── Extract: sentiment/tone (formal, urgent, friendly, dispute)        │
│  └── Tag: document category (letter, contract, financial, legal, etc.)  │
│                                                                         │
│  → Yield: Structured fact database per document                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PHASE 4: CROSS-DOCUMENT SYNTHESIS                                      │
│  ├── Merge facts: resolve aliases (Sow = Ousmane Sow = M. Sow)          │
│  ├── Build timeline: sort events chronologically                        │
│  ├── Build relationship graph: who interacts with whom, how often       │
│  ├── Detect patterns: recurring themes, escalating issues, changes      │
│  ├── Detect contradictions: conflicting statements across docs          │
│  └── Score importance: which facts appear most often / most recently    │
│                                                                         │
│  → Yield: Rich knowledge graph + timeline + pattern list                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PHASE 5: REPORT ARCHITECTURE (type-specific templates)                 │
│  ├── Person Profile Skill      → biography, career, network             │
│  ├── Organization Skill        → structure, contracts, financials       │
│  ├── Relationship Skill        → interaction history, sentiment arc     │
│  ├── Project Skill             → milestones, blockers, outcomes         │
│  └── Legal/Financial Skill     → obligations, risks, compliance         │
│                                                                         │
│  → Yield: Deep, sectioned report with quoted evidence                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Tactical Improvements (What to Build)

### 3.1 Integrate with Main Search Module as Primary Retrieval

**Current:** `RetrievalService` builds its own weak query and calls `search_service.hybrid_search()` as Signal 2.

**Improved:** Create a `DeepSearchRetriever` that:

```python
class DeepSearchRetriever:
    """Uses the main search module for comprehensive retrieval."""

    async def retrieve(self, query: str, entity_name: str, db, user) -> RetrievalContext:
        # 1. Semantic search with clean entity-focused queries
        semantic_results = await search_service.semantic_search(
            query=entity_name,  # "Ousmane Sow" — clean, no function words
            limit=50,
            db=db, user=user,
        )

        # 2. Semantic search with role/organization context
        if organization_hints := self._extract_orgs_from_query(query):
            for org in organization_hints:
                org_results = await search_service.semantic_search(
                    query=f"{entity_name} {org}",
                    limit=20,
                    db=db, user=user,
                )
                semantic_results.extend(org_results)

        # 3. Keyword search for exact name variants
        keyword_results = await search_service.keyword_search(
            query=f'"{entity_name}" OR "{self._initials_variant(entity_name)}"',
            limit=30,
            db=db, user=user,
        )

        # 4. Hybrid search with enriched query
        hybrid_results = await search_service.hybrid_search(
            query=entity_name,  # Just the entity — let the user query guide intent
            limit=50,
            rerank=True,
            db=db, user=user,
        )

        # 5. Merge, deduplicate, score
        merged = self._merge_and_rank(semantic_results, keyword_results, hybrid_results)

        # 6. Cluster by document to get full coverage
        doc_coverage = self._cluster_by_document(merged)

        return RetrievalContext(
            primary_assets=merged[:50],
            document_coverage=doc_coverage,  # {doc_id: [chunks]}
            total_found=len(merged),
        )
```

**Key differences from current approach:**
- Search query = `"Ousmane Sow"` (clean entity name) instead of `"me faire un mémo sur Ousmane Sow"`
- Multiple search strategies (semantic, keyword, hybrid) merged
- Returns chunk clusters per document (not just flat chunk list)

### 3.2 Full Document Reading Tool

**New Tool:** `document_reader.read_full(document_id)`

```python
class DocumentReaderTool:
    """Read full document content, not just chunks."""

    async def read(self, document_id: UUID, db: AsyncSession) -> dict:
        doc = await db.get(Document, document_id)
        chunks = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        full_text = "\n\n".join(c.chunk_text for c in chunks.scalars().all())

        return {
            "document_id": document_id,
            "title": doc.original_filename,
            "type": self._detect_doc_type(doc),
            "date": doc.created_at,
            "full_text": full_text[:15000],  # First 15K chars
            "metadata": doc.metadata,
            "tables": await self._extract_tables(doc),
        }
```

**Why this matters:**
- A 5-page letter about Ousmane Sow is split into 10 chunks. Reading all chunks together gives the LLM the full narrative arc.
- Tables (balance sheets, contract terms) are only meaningful when read in full.
- The LLM can infer sender/recipient/relationship from document structure.

### 3.3 Person-Centric Skill (`person_profile`)

Replace `general_narrative` with a **type-aware skill selector**:

```python
class PersonProfileSkill(BaseSkill):
    """Deep biography and relationship analysis for individuals."""

    skill_id = "person_profile"

    async def analyze(self, parameters, context) -> SkillResult:
        db = context["db"]
        entity_name = context["entity_name"]

        # 1. Deep search for all mentions
        search_results = await deep_search_retriever.retrieve(
            query=context["query"],
            entity_name=entity_name,
            db=db, user=context["user"],
        )

        # 2. Read full text of top-15 documents
        documents = []
        for doc_id in search_results.top_document_ids[:15]:
            doc = await document_reader.read(doc_id, db)
            documents.append(doc)

        # 3. Structured extraction via LLM (per document)
        facts_per_doc = []
        for doc in documents:
            extraction = await self._extract_facts(doc, entity_name)
            facts_per_doc.append(extraction)

        # 4. Cross-document synthesis
        biography = await self._synthesize_biography(facts_per_doc, entity_name)

        return SkillResult(
            skill_id=self.skill_id,
            success=True,
            raw_output={
                "title": f"Mémo sur {entity_name}",
                "summary": biography.executive_summary,
                "timeline": biography.career_timeline,
                "roles": biography.roles_by_organization,
                "relationships": biography.key_relationships,
                "documents": biography.document_inventory,
                "raw_markdown": biography.full_report,
            },
        )
```

**Report structure for a person:**

```markdown
# Mémo sur Ousmane Sow

## Profil Exécutif
Ousmane Sow est un dirigeant sénégalais actif dans le secteur énergétique...

## Chronologie Professionnelle
| Date | Événement | Source |
|------|-----------|--------|
| 2019-03 | Nommé Représentant de MATAUTO | [Contrat de représentation, doc-123] |
| 2021-07 | Promu Directeur Exécutif de Matenergy | [PV Assemblée, doc-456] |
| 2023-01 | Signature contrat fourniture électrique | [Contrat F-2023-01, doc-789] |

## Organisations & Rôles
- **Matenergy S.A.** — Directeur Exécutif (depuis 2021)
- **MATAUTO** — Représentant (2019-2022)
- **Groupe Sow Holdings** — Directeur Délégué

## Réseau de Relations
- **Mamadou Diallo** — Collègue, co-signataire sur 3 contrats
- **Aminata Ndiaye** — Correspondante régulière (12 lettres)
- **Banque Atlantique** — Relation bancaire active

## Documents Clés (23 trouvés)
### Contrats (5)
- Contrat de fourniture électrique Matenergy-CIE [doc-789] — 15 pages
- ...

### Correspondance (8)
- Lettre de Ousmane Sow à M. Diop [doc-234] — 2022-04-12
- ...

### Financiers (4)
- Bilan Matenergy 2022 [doc-567] — Ousmane Sow signataire
- ...

## Observations & Recommandations
- **Contrat F-2023-01** arrive à échéance en janvier 2024 — renouvellement à suivre
- Relation avec **MATAUTO** semble s'être terminée en 2022 (dernier document)
```

### 3.4 Multi-Hop Graph Expansion

**Current:** Graph traversal only goes depth-1 via `EntityRelationship`.

**Improved:** Dynamic graph expansion during retrieval:

```python
async def expand_graph(self, entity_id: UUID, db: AsyncSession, depth: int = 2):
    """Dynamically discover relationships from document content."""
    # 1. Get all documents mentioning the entity
    docs = await self._get_documents_for_entity(entity_id, db)

    # 2. For each document, extract co-mentioned entities
    related = defaultdict(int)
    for doc in docs:
        co_mentions = await self._extract_co_mentions(doc, entity_id)
        for co_id in co_mentions:
            related[co_id] += 1

    # 3. Retrieve documents for top co-mentioned entities
    top_related = sorted(related.items(), key=lambda x: x[1], reverse=True)[:10]
    for co_id, freq in top_related:
        co_docs = await self._get_documents_for_entity(co_id, db)
        # These documents provide CONTEXT about the primary entity
```

**Example:**
- Document: "Ousmane Sow (Matenergy) and Mamadou Diallo (CIE) signed contract X"
- Entity extraction finds: Ousmane Sow ↔ Mamadou Diallo (co-occurrence)
- Even if no `EntityRelationship` exists in KG, we discover the connection
- Retrieve documents about Mamadou Diallo → learn about Contract X details

### 3.5 Rich Prompting with Evidence Quoting

**Current prompt:**
```
Context: [chunk1] [chunk2] [chunk3]
Generate a report with title, summary, timeline...
```

**Improved prompt:**
```
You are a senior analyst writing a confidential memo. You have read the following
primary source documents. Cite specific passages using [Document: Title, Page N].

DOCUMENTS:
---
[Document: Lettre_Diop_2022.pdf, Page 1]
"Cher Monsieur Sow, en ma qualité de Directeur Exécutif de Matenergy..."
---
[Document: Contrat_F2023.pdf, Page 3]
"Le soussigné Ousmane Sow, agissant en qualité de Représentant de MATAUTO..."
---

INSTRUCTIONS:
1. Only state facts supported by the documents above.
2. Quote key passages verbatim to support each claim.
3. Note uncertainty: "Selon le document X, Sow serait..." vs "Sow est confirmé comme..."
4. Organize by theme: Professional Role, Chronology, Relationships, Documents.
5. Flag any contradictions between documents.
6. Write in the language of the query (French).
```

### 3.6 Document Type Awareness

Add a `document_classifier` tool that categorizes documents:

| Type | Extraction Priority |
|------|-------------------|
| `contract` | Parties, dates, amounts, obligations, signatures |
| `letter` | Sender, recipient, date, subject, tone, action items |
| `financial_statement` | Period, key figures, ratios, auditor notes |
| `legal_notice` | Jurisdiction, deadlines, parties, claims |
| `meeting_minutes` | Attendees, decisions, action items, deadlines |
| `email` | Thread participants, attachments, urgency |

The skill should **adapt its extraction strategy** based on document type.

---

## 4. Data Quality & Pipeline Improvements

### 4.1 Backfill Entity Mentions

Run a batch job to re-extract entities from all documents using the latest NER model:

```python
# One-time backfill
for doc in all_documents:
    chunks = get_chunks(doc)
    for chunk in chunks:
        entities = ner_service.extract(chunk.text)
        for ent in entities:
            if ent.type == "PERSON" and ent.confidence > 0.7:
                create_or_update_entity_mention(
                    document_id=doc.id,
                    entity_id=resolve_entity(ent.name),
                    context_text=chunk.text,
                    confidence_score=ent.confidence,
                )
```

### 4.2 Populate Milestones from Documents

Auto-extract dated events for each entity:
- "Nommé Directeur le 15 mars 2021" → Milestone(date=2021-03-15, title="Nomination Directeur")
- "Contrat signé le 1er janvier 2023" → Milestone(date=2023-01-01, title="Signature contrat")

Use LLM with few-shot prompting to extract events from full documents.

### 4.3 Pre-Compute Entity Summaries

For frequently queried entities, pre-compute and cache:
- Entity profile (roles, orgs, key dates)
- Top 20 related documents
- Relationship network
- Communication frequency over time

Store in `entity_summaries` table. Smart Folder can serve cached summaries instantly.

---

## 5. UX Enhancements

### 5.1 Interactive Report Builder

Instead of a static report, show an **interactive dashboard**:

```
┌─────────────────────────────────────────────┐
│  Mémo sur Ousmane Sow        [Export PDF]   │
├─────────────────────────────────────────────┤
│  [Timeline] [Documents] [Network] [Raw]     │
├─────────────────────────────────────────────┤
│                                             │
│  📊 Timeline Visualization                  │
│  2019 ──●── 2021 ──●── 2023 ──●──►         │
│       Repr.   Promo   Contrat               │
│                                             │
│  📁 23 Documents trouvés                    │
│  [Contracts ▼] [Letters ▼] [Financial ▼]    │
│                                             │
│  🕸️ Network                                │
│  [Ousmane Sow]───[Matenergy]               │
│       │              │                      │
│   [M. Diallo]───[CIE]                      │
│                                             │
└─────────────────────────────────────────────┘
```

### 5.2 Source Transparency

Every sentence in the report should be **hoverable** to show:
- Source document name
- Page number
- Exact quoted passage
- Confidence score

### 5.3 Refinement by Section

Instead of a single refinement bar, allow users to:
- "Add more detail about his role at Matenergy"
- "Show me only financial documents"
- "What happened in 2022 specifically?"

Each refinement triggers a targeted sub-search and report section update.

---

## 6. Implementation Roadmap

### Phase A: Quick Wins (1-2 weeks)
1. **Fix search query quality** — strip function words from entity search queries
2. **Fix `__USAGE__` metadata stripping** — already done ✅
3. **Fix duplicate entity resolution** — already done ✅
4. **Add raw query fallback** — already done ✅
5. **Increase retrieval limits** — `hybrid_limit=50`, `mention_limit=50`
6. **Read full documents** — feed top-10 document full texts to report generator

### Phase B: Search Integration (2-3 weeks)
1. Build `DeepSearchRetriever` using main search module
2. Build `DocumentReaderTool` for full-text reading
3. Build `DocumentClassifierTool`
4. Update `general_narrative` skill to use deep search + full reading

### Phase C: Type-Aware Skills (3-4 weeks)
1. Build `PersonProfileSkill` with biography template
2. Build `OrganizationProfileSkill`
3. Build `RelationshipTimelineSkill`
4. Build `ProjectPostmortemSkill` (enhance existing)
5. Update planner to select skill based on entity type

### Phase D: Data Pipeline (4-6 weeks)
1. Backfill entity mentions across all documents
2. Auto-extract milestones from documents
3. Pre-compute entity summaries
4. Build entity relationship co-occurrence graph

### Phase E: UX Polish (2-3 weeks)
1. Interactive timeline component
2. Document filter panel
3. Network graph visualization
4. Section-level refinement

---

## 7. Summary

| Problem | Solution | Priority |
|---------|----------|----------|
| Retrieval misses 80% of mentions | Integrate main search module | 🔴 Critical |
| Only chunk snippets, no full docs | `DocumentReaderTool` — read full text | 🔴 Critical |
| Generic skill, no type awareness | `PersonProfileSkill`, `OrgProfileSkill` | 🟡 High |
| No cross-document synthesis | Multi-hop graph + fact merging | 🟡 High |
| Empty milestones/patterns tables | Auto-extract from documents | 🟢 Medium |
| Thin report with no evidence | Rich prompting + evidence quoting | 🔴 Critical |
| No document type awareness | `DocumentClassifierTool` | 🟡 High |

**The single most impactful change:** Replace the entity-mention-centric retrieval with **deep search + full document reading**. This alone would transform the Ousmane Sow report from 2 sentences to a rich, multi-section memo with timelines, roles, organizations, and quoted evidence.
