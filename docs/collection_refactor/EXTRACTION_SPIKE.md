# Extraction Spike — Accuracy Baseline (Phase 0)

Date: 2026-08-02. Method: read-only sample of 50 chunks (spread across the 200 most
recent `document_chunks` with `length(chunk_text) >= 200`) from the live database,
processed inside the `sowknow-backend` container with:

- `TableExtractorTool` (`backend/app/services/smart_folder/tools/table_extractor.py`)
  — markdown/CSV table parsing (existing, reused as-is)
- Regex extraction: numbers (thousands-separator aware), percentages, currency
  amounts (€/$/£/XOF/FCFA/EUR/USD/GBP), dates (ISO, d/m/y, month-name, bare year)

## Results

| Metric | Value |
|---|---|
| Chunks sampled | 50 |
| Chunks with extractable tables | 23 (46%) |
| Chunks with numeric facts | 39 (78%) |
| Chunks with dates | 27 (54%) |
| Chunks with percentages | 1 (2%) |
| Chunks with currency amounts | 2 (4%) |
| Raw facts extracted (numbers + dates) | 2,195 |
| Avg raw facts / chunk | 43.9 |
| Table cells extracted | 459 |

## Findings that shape the Extraction Pipeline (FR4.1)

1. **Raw regex over-matches badly.** ~44 raw "facts"/chunk includes IDs, phone-like
   sequences, years, line numbers. The pipeline must score and filter: a number only
   becomes a fact when it carries context (nearby label/unit/keyword) — otherwise the
   FactSet drowns in noise and FR4.1.6's confidence threshold (default 0.7) would be
   meaningless. Confidence = f(has_label, has_unit, in_table, source_type).
2. **Tables survive as markdown in ~half of structured chunks.** Excel-derived chunks
   often carry numbers *without* markdown table structure (3 of 8 sampled docs:
   numbers > 0, tables = 0). Table extraction alone is insufficient; prose/regex
   extraction with label proximity is the primary path, tables are the high-confidence
   path (confidence boost when a fact comes from a parsed table cell).
3. **Currency/percent density is low in this corpus** (personal vault: xls exports,
   PDFs). Unit normalisation (FR4.1.7) still required but will trigger rarely; currency
   symbols in this corpus are mostly absent — amounts are bare numbers whose unit must
   come from column headers / nearby labels.
4. **Empty-content chunks exist** (2 of 8 sampled docs had zero numbers and zero
   dates — likely image-only or scanned content). These map to FR6.6 "content
   unavailable — excluded from analysis" and must be counted in the extraction success
   rate metric (FR8.2), not silently dropped.

## Baseline conclusion

Extraction is feasible with existing tools + context-scored regex extraction.
Baseline for Phase 1 acceptance: ≥78% of sampled chunks yield at least one
confidence-scored fact; table-bearing chunks yield structured rows at 100% parse
success. OCR/scanned chunks are excluded from computation and disclosed (FR4.1.6).
