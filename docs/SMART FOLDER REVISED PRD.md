SMART FOLDER REVISED PRD

\> You are refactoring the “Smart Folder” module of the \*\*Smart Digital Vault\*\* app. The current implementation is poorly understood and fails to meet the user’s needs. Your goal is to re-architect and rebuild this module according to the attached PRD. The core capability: given a natural-language request like \*“I want an article about my relationship with Bank A”\*, the system must search all assets (files, notes, milestones, patterns, trends, issues, learnings – accumulated over 40 years) and produce a deep, personalised report with full citation links. The output must adapt its structure, tone, and content to the type of relationship (institutional, personal, professional) and the user’s intent. Treat every factual claim as requiring a direct, clickable link to the source vault item. Use the following PRD as your sole specification.

\---

\#\# Product Requirements Document (PRD): Smart Folder Module v2

\#\#\# 1\. Executive Summary  
The Smart Folder is not a physical folder – it is an \*\*on‑demand, natural‑language‑driven report generator\*\*. It turns the user’s 40‑year digital treasure trove into actionable intelligence by finding all relevant assets, extracting timelines, patterns, risks, and insights, and composing a coherent, cited synthesis tailored to the queried relationship or topic.

\#\#\# 2\. Problem Statement (Why the current module fails)  
\- The AI assistant does not grasp that Smart Folder is a dynamic content generation feature, not a static container.  
\- There is no clear pipeline from natural language to entity resolution, retrieval, multi‑faceted analysis, and structured generation.  
\- Citations are missing or not linked to real vault items.  
\- The module does not differentiate between a professional relationship (bank, employer) and a personal one (friend, relative) – tone and content must shift accordingly.  
\- Users cannot refine their initial query iteratively.

The refactoring must replace the current module with an entirely new, end‑to‑end pipeline as specified below.

\#\#\# 3\. Key Concepts & Definitions  
| Term | Definition |  
|------|------------|  
| \*\*Vault\*\* | The complete, encrypted store of all user digital assets: documents, images, emails, calendar entries, notes, contacts, manually defined milestones, auto‑detected patterns/trends/issues/learnings. |  
| \*\*Smart Folder\*\* | A generated, transient (optionally saveable) document that answers a natural‑language request by synthesising findings from the Vault, with full source citations. |  
| \*\*Entity\*\* | A named person, organisation, project, or concept that the system tracks (e.g., “Bank A”, “John”, “Project Phoenix”). |  
| \*\*Relationship Type\*\* | Professional, Personal, Institutional, Project‑based, etc. – inferred from context and entity attributes. |  
| \*\*Milestone\*\* | A significant dated event linked to one or more entities (e.g., “Opened account with Bank A – 15 Mar 2010”). |  
| \*\*Pattern\*\* | A recurring behaviour or theme (e.g., “monthly maintenance fee deducted”). |  
| \*\*Trend\*\* | A directional change over time (e.g., “increasing frequency of support calls”). |  
| \*\*Issue\*\* | A documented problem or complaint (e.g., “disputed charge in Jan 2022”). |  
| \*\*Learning\*\* | A user‑written or auto‑extracted personal takeaway (e.g., “Always confirm wire transfer fees beforehand”). |  
| \*\*Citation\*\* | A clickable reference in the report that links directly to the source vault item (with contextual preview). |

\#\#\# 4\. User Stories  
1\. \*\*Discover insights\*\* – \*“Tell me about my relationship with Bank A”\* → I get a report covering all interactions, milestones, financial patterns, risks, and recommendations, with every claim linked to an original email/statement/note.  
2\. \*\*Context‑aware tone\*\* – The same request for \*“my friend Jane”\* yields a personal history, shared memories, and emotional highlights, while \*“my accountant Jane”\* focuses on financial advice, tax filings, and professional reliability.  
3\. \*\*Iterate on request\*\* – After seeing the report, I type \*“Focus only on mortgage dealings”\* and the system regenerates a narrower report.  
4\. \*\*Save & revisit\*\* – I can save a Smart Folder as a permanent note that I can open and refresh later.  
5\. \*\*Trust through citations\*\* – I can click any superscript citation number and immediately view the source item (e.g., email) in a side panel, confirming the information.

\#\#\# 5\. Functional Requirements (FR)

\#\#\#\# FR1: Natural Language Input  
\- A single text input field (prompt) that accepts any natural-language request.  
\- Examples: \*“I want an article about my relationship with Bank A”\*, \*“Summarise the Smith project”\*, \*“What are my most important lessons from interacting with John?”\*

\#\#\#\# FR2: Query Understanding & Entity Resolution  
\- Parse the request using an LLM to extract:  
  \- \*\*Primary Entity\*\* (e.g., “Bank A”)  
  \- \*\*Relationship Type\*\* (professional, personal, institutional, project, etc.)  
  \- \*\*Temporal scope\*\* (implicit “all time” unless specified, e.g., “last 5 years”)  
  \- \*\*Focus aspects\*\* (if any): financial, legal, emotional, etc.  
\- Resolve entity name to internal entity ID using exact match, aliases, and fuzzy matching (handle “Bank A”, “BankA”, “Bank A Ltd.”).

\#\#\#\# FR3: Multi‑Signal Retrieval  
Search the Vault for all items related to the entity and the derived intent. Combine:  
\- Direct tags/mentions (entity explicitly linked)  
\- Full‑text search (entity name appears in content)  
\- Semantic/embedding search for conceptually related items  
\- Graph traversal: items linked to people/projects connected to the target entity  
\- Temporal filter if specified  
Result: a ranked, deduplicated list of vault assets (documents, notes, emails, calendar entries, etc.).

\#\#\#\# FR4: Analysis Layer – Extract Structured Findings  
For each retrieved asset and across the set, extract / aggregate:  
\- \*\*Milestones\*\* (from pre‑tagged milestone objects or detected key events)  
\- \*\*Patterns\*\* (recurring topics, behaviours)  
\- \*\*Trends\*\* (numeric sequences like balances, communication frequency)  
\- \*\*Issues\*\* (documented problems, flagged items)  
\- \*\*Learnings\*\* (user‑annotated insights)  
Contextual analysis must be re‑run or filtered per query to align with the entity and requested scope.

\#\#\#\# FR5: Content Generation – Structured Report  
Using a generative LLM, produce a report containing (sections may be omitted if irrelevant):  
1\. \*\*Title\*\* – e.g., “Smart Folder: Relationship with Bank A”  
2\. \*\*Executive Summary\*\* – 2‑3 sentence overview  
3\. \*\*Timeline of Key Milestones\*\* – chronological table or list  
4\. \*\*Pattern & Trend Analysis\*\* – bullet points describing what repeats or changes  
5\. \*\*Issues & Risks\*\* – documented problems and potential future risks  
6\. \*\*Personal Learnings & Recommendations\*\* – insights the user recorded and advice derived from them  
7\. \*\*Citation Index\*\* – all references collected at the end (or displayed inline)

Every factual statement \*\*must\*\* be immediately followed by a citation anchor like \`\[1\]\`, which maps to a source asset.

\#\#\#\# FR6: Citation Linking & Context  
\- Each \`\[N\]\` is a clickable link that opens the corresponding vault item (detail view or popover) with the relevant passage highlighted.  
\- Citations include a short preview snippet in the report footer for transparency.

\#\#\#\# FR7: Relationship‑Type Adaptation  
The LLM prompt must include explicit instructions based on the detected relationship type:  
\- \*\*Personal (friend/family):\*\* warm tone, include photos/events, highlight emotional significance, shared experiences.  
\- \*\*Professional (colleague/accountant):\*\* formal tone, focus on work delivered, reliability, contractual outcomes.  
\- \*\*Institutional (bank, company):\*\* factual, financial detail, contract terms, risk assessment.  
\- \*\*Project:\*\* milestones, deliverables, blockers, team contributions.

\#\#\#\# FR8: Iterative Refinement  
\- Smart Folder view retains the original query and allows a new prompt to \*\*refine\*\* the same entity/report (e.g., “Limit to 2020‑2023”, “Only show disputes”).  
\- The system re‑runs retrieval \+ generation with the added constraints without restarting from scratch (cache previous context).

\#\#\#\# FR9: Persistence  
\- Option to “Save as Note”, which stores the full generated content, query parameters, and version timestamp.  
\- Saved Smart Folders can be regenerated (updated) on demand.

\#\#\#\# FR10: Privacy & On‑Device Processing  
\- All query processing, entity resolution, and content generation must respect end‑to‑end encryption; no raw data leaves the user’s trust boundary (local LLM or approved private cloud with zero‑retention).

\#\#\# 6\. Non‑Functional Requirements  
\- \*\*Performance:\*\* For a vault of 100k assets, the pipeline must complete within 30 seconds, showing a progress indicator (retrieving → analysing → generating).  
\- \*\*Accuracy & Hallucination Guard:\*\* LLM must be constrained to use \*only\* the provided context; any unsupported claim is a failure.  
\- \*\*Scalability:\*\* Vault may grow to millions of items; retrieval must use indexes (full‑text, vector) and not scan linearly.  
\- \*\*Usability:\*\* Input field must feel like asking a question; output must be a clean, rich document with a floating table of contents.

\#\#\# 7\. Data Model & Dependencies  
\- \*\*VaultAsset:\*\* \`id, type, title, textExtract, createdDate, entities\[\], tags\[\]\`  
\- \*\*Entity:\*\* \`id, name, aliases\[\], type(person/org/project)\`  
\- \*\*Milestone:\*\* \`date, title, description, linkedAssets\[\], entityId\`  
\- \*\*Pattern/Insight:\*\* \`type(Trend/Issue/Learning), description, linkedAssets\[\], entityId, confidence\`  
\- \*\*SmartFolderReport:\*\* \`id, queryText, generatedContent(json/richtext), sourceAssetIds\[\], createdAt, entityId\`

\#\#\# 8\. High‑Level Architecture / Algorithm Steps  
1\. \*\*Parse Query\*\* → LLM extracts \`{ entity, relationType, timeRange, focus }\`  
2\. \*\*Resolve Entity\*\* → Map to canonical Entity ID via alias table.  
3\. \*\*Retrieve Assets\*\* → Hybrid search (keyword \+ vector \+ graph) limited to entity and optional time filter.  
4\. \*\*Gather Structured Data\*\* → Fetch all milestones, patterns, trends, issues, learnings linked to those assets and the entity.  
5\. \*\*Build LLM Context\*\* → Assemble a concise, structured string containing entity profile, timeline, patterns, issues, and raw asset snippets (with source IDs).  
6\. \*\*Generate Report\*\* → Prompt LLM with strict instruction:  
   \`\`\`  
   You are generating a validity-checked report. Use ONLY the provided context.   
   End every factual sentence with a citation marker like \[AssetID\].  
   Structure: Title, Summary, Timeline, Patterns, Issues, Learnings, Recommendations.  
   Tone: {adjusted per relationship type}.  
   \`\`\`  
7\. \*\*Post‑Process\*\* → Replace \`\[AssetID\]\` with clickable citation numbers; attach full source previews.  
8\. \*\*Render\*\* → Rich document UI with interactive citations.

\#\#\# 9\. UI/UX Wireframe (Textual)  
\- \*\*Trigger:\*\* Top search bar with placeholder \*“Ask about any relationship, project, or topic…”\* and a ‘Generate’ button.  
\- \*\*Loading:\*\* Skeleton cards with step labels: “Finding assets…”, “Extracting milestones…”, “Writing report…”  
\- \*\*Result View:\*\* Collapsible sections, numbered citation superscripts; click opens a right‑side panel with the original asset.  
\- \*\*Refinement Bar:\*\* Below the report, an input field with hint \*“Refine this report…”\*  
\- \*\*Actions:\*\* ‘Save as Note’, ‘Copy’, ‘Share’ (encrypted).

\#\#\# 10\. Acceptance Criteria  
1\. A query for \*“my relationship with Bank A”\* produces a report with a timeline of interactions, financial trends, issues, and recommendations, each statement backed by a clickable vault reference.  
2\. The report for \*“my friend Jane”\* differs in tone and content from \*“my accountant Jane”\* for the same entity name.  
3\. A refinement query \*“only show disputes”\* regenerates a report filtered accordingly.  
4\. Clicking a citation opens the exact source asset with the relevant text highlighted.  
5\. The entire flow takes \<30 seconds for a vault of 100k assets on a mid‑tier device.  
6\. No factual statement exists without a valid source anchored to a real vault item.

\#\#\# 11\. Edge Cases  
\- Entity not recognised → prompt user to confirm or add mapping.  
\- No assets found → generate a report stating “No records for this entity” with suggestions to broaden search.  
\- Extremely long timelines → summarise with expandable detail.  
\- Simultaneous conflicting evidence → the LLM must note contradictions with citations rather than favouring one.

\#\#\# 12\. Implementation Phases (Suggested)  
\- \*\*Phase 1 – Core Pipeline:\*\* Query parsing, entity resolution, basic retrieval, plain‑text report generation with citations.  
\- \*\*Phase 2 – Relationship Adaptation & Analytics:\*\* Connect true milestone/pattern data, adapt tone, save/load.  
\- \*\*Phase 3 – Refinement & Advanced UI:\*\* Iterative query, rich citations panel, caching for performance.

\#\#\# 13\. Risks & Mitigations  
| Risk | Mitigation |  
|------|------------|  
| LLM hallucinates facts not in context | Strict prompting, post‑verification of each citation’s existence, fallback to “Insufficient data” |  
| Retrieval misses key assets | Use multiple retrieval strategies; allow manual addition of missing items via UI |  
| Query latency too high | Pre‑compute and cache entity summaries; incremental generation with streaming |  
| Privacy breach | Ensure all processing in zero‑retention environment; all assets remain encrypted |

\---

You're absolutely right. The Smart Folder module shouldn't just be a passive reporter — it should be an \*\*agentic orchestrator\*\* that can wield specific skills (financial analysis, legal reasoning, sentiment tracking, etc.) and tools (spreadsheet parsers, chart generators, external APIs) to produce genuinely professional, domain‑deep output. Let’s turn that insight into a concrete addendum you can hand directly to the AI assistant alongside the original PRD.

\---

\#\# Enhanced Prompt (to be given to the AI assistant before the PRD)

\> You are refactoring the Smart Folder module of the Smart Digital Vault app. The attached PRD describes the core pipeline: natural language → entity resolution → asset retrieval → structured analysis → report generation with citations. However, that pipeline must now evolve into an \*\*agentic system\*\*. The user can request analyses that go far beyond simple summarisation — for example, “Analyse the balance sheets of Company X over the last 5 years”. In such cases, the system must autonomously select and invoke specialised \*\*skills\*\* (e.g., FinancialStatementAnalyser) and \*\*tools\*\* (e.g., balance sheet parser, ratio calculator, chart renderer) to produce a meaningful, professional result. The PRD addendum below fully specifies this agentic architecture. Implement the Smart Folder v2.1 as an agentic module according to the combined specification.

\---

\# Smart Folder Agentic Architecture – PRD Addendum

\#\# 1\. Why Agentic?  
The original Smart Folder v2 pipeline does one thing well: it finds related assets, extracts generic milestones/issues/learnings, and compiles a report. But when a user asks a \*\*domain‑specific quantitative or qualitative question\*\* — like “Analyse the balance sheets of my company from 2019 to 2024” — the system must:

\- Identify that this is a \*\*financial analysis task\*\*.  
\- Locate and open the relevant spreadsheet/PDF balance sheets.  
\- Extract structured financial data (assets, liabilities, equity, ratios).  
\- Perform trend calculations, liquidity/solvency analysis, and possibly even a DCF or growth assessment.  
\- Generate charts (e.g., asset vs liability trends).  
\- Write a professional CFO‑grade commentary, citing specific sheet locations.

A static LLM prompt cannot do this reliably. An \*\*agentic architecture\*\* with a planner and a toolbox can.

\#\# 2\. Agent Core (the “Smart Folder Agent”)  
The Smart Folder becomes an \*\*autonomous agent\*\* with the following loop:

1\. \*\*Understand intent\*\* → Classify the request type (general narrative, financial analysis, legal review, project post‑mortem, etc.) and extract parameters (entity, time frame, focus).  
2\. \*\*Plan\*\* → Decompose the request into sub‑tasks, each mapped to a skill from the Skill Registry.  
3\. \*\*Execute\*\* → Invoke skills sequentially or in parallel; skills use Tools to interact with vault items, perform calculations, and generate intermediate artefacts.  
4\. \*\*Synthesise\*\* → Gather all skill outputs, feed them into a final report‑generation LLM call (with strict citation rules) to produce the finished Smart Folder.  
5\. \*\*Reflect (optional)\*\* → If any skill fails or returns low confidence, the agent can replan and retry.

This agent operates \*\*on‑device or in a zero‑retention private environment\*\*.

\#\# 3\. Skill Registry  
Skills are domain‑specific sub‑agents, each with a clear capability description, required inputs, and output schema. The agent selects skills dynamically based on the classified intent.

| Skill ID | Skill Name | When Used | Key Actions |  
|-----------|-------------|-----------|-------------|  
| \`general\_narrative\` | General Relationship Narrator | Default for personal/professional summaries | Timelines, pattern extraction, lesson integration |  
| \`financial\_analysis\` | Financial Statement Analyser | Queries mentioning “balance sheet”, “P\&L”, “cash flow”, “financial health” | Parse structured financial docs, compute ratios, trend tables, chart generation |  
| \`legal\_review\` | Contract / Legal Document Analyser | Requests like “review NDA with Vendor Y” or “check compliance” | Clause extraction, obligation listing, risk flagging |  
| \`project\_postmortem\` | Project Retrospective | “How did Project Alpha go?” | Milestone vs actual comparison, blocker analysis, team contribution summary |  
| \`health\_tracker\` | Personal Health & Medical Summary | “My medical history with Dr. Smith” | Timeline of visits, test result trends, medication changes |  
| \`sentiment\_tracker\` | Communication Sentiment Analyser | Overlaying sentiment on email/SMS threads | Polarity over time, relationship health index |  
| \`custom\_query\` | Unstructured Deep Search | Fallback for novel requests | Vector+keyword search, LLM‑powered Q\&A over raw assets |

Each skill can call common tools and return a structured \*\*SkillResult\*\* containing:  
\- Text summary  
\- Data tables (CSV/JSON)  
\- Visualisation references (chart images or Vega‑Lite specs)  
\- Source citations with precise location anchors

\#\# 4\. Tool Pool  
Tools are low‑level capabilities that skills call to interact with the vault and perform computations. They are not user‑facing.

| Tool ID | Tool Name | Description |  
|----------|-----------|-------------|  
| \`vault\_search\` | Hybrid Vault Search | The same multi‑signal retrieval engine from the base PRD (keyword, vector, graph). |  
| \`asset\_reader\` | Asset Content Extractor | Given a vault asset ID, returns full text, metadata, and any embedded tabular data. Supports PDFs, spreadsheets, images (via OCR). |  
| \`table\_extractor\` | Structured Table Parser | Extracts tables from spreadsheets/PDFs into pandas‑like dataframes (column names, data types). |  
| \`ratio\_calculator\` | Financial Ratio Engine | Computes liquidity, solvency, profitability, efficiency ratios from balance sheet / income statement tables. |  
| \`trend\_analyzer\` | Time‑Series Trend Detector | Takes numeric arrays and returns linear regression, YoY growth, volatility, anomalies. |  
| \`chart\_generator\` | On‑device Chart Renderer | Produces line, bar, waterfall, pie charts from tables; outputs image or Vega‑Lite JSON for the UI. |  
| \`citation\_marker\` | Citation Linker | Tags each piece of evidence with the exact asset ID and cell/section reference. |  
| \`refinement\_parser\` | Intent Refiner | Used in iterative queries to merge new constraints with the original plan. |

Tools are stateless and called via a secure internal API.

\#\# 5\. Example Walkthrough: “Analyse the balance sheets of Company X over the last 5 years”

1\. \*\*Intent Classification\*\*    
   → \`financial\_analysis\` skill selected. Entity \= “Company X”, time \= 2019–2024, documents \= balance sheets.

2\. \*\*Planning\*\*    
   Agent creates plan:  
   \- Step 1: Retrieve all balance sheet files for Company X in date range.    
   \- Step 2: For each, use \`table\_extractor\` to get structured data.    
   \- Step 3: Align common line items across years, normalise naming.    
   \- Step 4: Use \`ratio\_calculator\` to compute current ratio, debt‑to‑equity, ROA, etc.    
   \- Step 5: Use \`trend\_analyzer\` to detect growth/decline in key items.    
   \- Step 6: \`chart\_generator\` to create trend charts (assets, liabilities, equity).    
   \- Step 7: Call the report LLM with all this structured data plus raw file citations.

3\. \*\*Execution\*\*    
   Each step calls the necessary tools. The \`financial\_analysis\` skill receives a summary of tables, ratios, trends, and chart references. It may even use a small local LLM to draft the initial analytical commentary, noting unusual items.

4\. \*\*Synthesis\*\*    
   The agent’s final composer LLM receives the skill output plus the original vault asset snippets. It writes the Smart Folder report:  
   \- Executive summary (financial health over time)  
   \- Key Findings: “Current ratio declined from 1.8 to 1.1, indicating liquidity pressure.”  
   \- Charts embedded  
   \- Each statement backed by \`\[AssetID:Sheet:Cell\]\` citations, e.g., \`\[doc\_4567:BS2021:B12\]\`

5\. \*\*Refinement\*\*    
   User asks: “Show me only the debt‑related trends.” The agent replans, re‑invokes \`trend\_analyzer\` on the debt subset, and regenerates the section.

\#\# 6\. Integration with Base Smart Folder PRD  
\- The base PRD’s \*\*FR2 (query understanding)\*\* is expanded to include intent classification and skill selection.  
\- \*\*FR3 (retrieval)\*\* and \*\*FR4 (analysis)\*\* are now executed by the skill/tool layer, not a monolithic pipeline.  
\- \*\*FR5 (content generation)\*\* becomes the final synthesis step that merges skill outputs.  
\- The agentic loop handles \*\*FR8 (iterative refinement)\*\* more gracefully by re‑planning with cached intermediate results.  
\- The UI must now support displaying charts, tables, and interactive tooltips for cell‑level citations (asset viewer integration).

\#\# 7\. New Acceptance Criteria (agentic extension)  
7\. \*\*Agentic Skill Selection\*\* – When a user asks “Analyse the balance sheets of Company X”, the agent selects the \`financial\_analysis\` skill, never the general narrator.  
8\. \*\*Financial Analysis Depth\*\* – The resulting report includes computed ratios (current ratio, debt‑to‑equity), at least one trend chart, and cell‑level citations from the original balance sheet files.  
9\. \*\*Fallback to General\*\* – If no specialised skill matches, the agent gracefully falls back to \`general\_narrative\` and still produces a high‑quality, cited report.  
10\. \*\*Tool Isolation\*\* – Each tool operates only on data explicitly passed from the vault; no external data leaks.  
11\. \*\*Iterative Financial Refinement\*\* – After the initial balance sheet report, the user can type “Focus only on asset growth” and the agent replans, only recomputing and re‑charting the asset trends.

\#\# 8\. Skill & Tool Development Guidelines (for implementation)  
\- Skills must be added as \*\*pluggable modules\*\* with a standard interface: \`analyze(parameters, context) → SkillResult\`  
\- The Smart Folder Agent’s planner is an LLM (fine‑tuned prompt) that outputs a JSON task list referencing skill IDs and parameters.  
\- Tools must be deterministic, verifiable, and fully local where possible (e.g., a Python‑based ratio calculator, a lightweight chart library).  
\- Every intermediate citation must be preserved through the pipeline; the \`citation\_marker\` tool wraps raw evidence with metadata.

\#\# 9\. Visualisation of Agentic Flow

\`\`\`  
User Request  
    │  
    ▼  
Intent Classifier \+ Planner ──► Plan (list of skills)  
    │  
    ▼  
Skill Executor ──► Skill 1 (financial\_analysis)  
                   │  
                   ├─► tool: vault\_search  
                   ├─► tool: table\_extractor  
                   ├─► tool: ratio\_calculator  
                   └─► tool: chart\_generator  
    │  
    ▼  
Skill Result Aggregator  
    │  
    ▼  
Final LLM Synthesizer (with citation rules)  
    │  
    ▼  
Smart Folder Report (text \+ charts \+ citations)  
\`\`\`

\---

By adding this agentic layer, the Smart Folder evolves from a document generator into a \*\*true digital analyst\*\* that can handle almost any reasoning task your 40‑year vault can support. Give this combined PRD to your AI assistant and it’ll know exactly what to build.  
