"use client";

interface CitationEntry {
  number: number;
  asset_id: string;
  preview: string;
  document_name?: string;
  page_number?: number | null;
  evidence_grade?: string | null;
  confidence_score?: number | null;
  relation_path?: string | null;
}

interface CitationPanelProps {
  citationIndex: Record<string, CitationEntry>;
  activeCitation: string | null;
  onClose: () => void;
}

const GRADE_COLORS: Record<string, string> = {
  A: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300 border-emerald-200 dark:border-emerald-700",
  B: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-700",
  C: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-700",
  D: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300 border-orange-200 dark:border-orange-700",
};

const GRADE_LABELS: Record<string, string> = {
  A: "Direct",
  B: "Related",
  C: "Co-occurrence",
  D: "Contextual",
};

export default function CitationPanel({ citationIndex, activeCitation, onClose }: CitationPanelProps) {
  const entries = Object.values(citationIndex).sort((a, b) => a.number - b.number);

  // Compute quality summary
  const gradeCounts: Record<string, number> = { A: 0, B: 0, C: 0, D: 0, "?": 0 };
  let totalConfidence = 0;
  let confidenceCount = 0;
  entries.forEach((e) => {
    const g = e.evidence_grade || "?";
    gradeCounts[g] = (gradeCounts[g] || 0) + 1;
    if (e.confidence_score != null) {
      totalConfidence += e.confidence_score;
      confidenceCount++;
    }
  });
  const avgConfidence = confidenceCount > 0 ? Math.round((totalConfidence / confidenceCount) * 100) : null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
      />
      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-full max-w-md bg-white dark:bg-gray-800 shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Sources & Citations
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition"
          >
            <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Quality Summary */}
        <div className="px-6 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/30">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              Source Quality
            </span>
            {avgConfidence !== null && (
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                Avg confidence: {avgConfidence}%
              </span>
            )}
          </div>
          <div className="flex gap-2 flex-wrap">
            {(["A", "B", "C", "D"] as const).map((g) =>
              gradeCounts[g] > 0 ? (
                <span
                  key={g}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${GRADE_COLORS[g]}`}
                >
                  <span className="font-bold">{g}</span>
                  <span>{GRADE_LABELS[g]}</span>
                  <span className="opacity-70">({gradeCounts[g]})</span>
                </span>
              ) : null
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {entries.length === 0 && (
            <p className="text-sm text-gray-500 dark:text-gray-400">No citations available.</p>
          )}
          {entries.map((entry) => {
            const grade = entry.evidence_grade || "?";
            const gradeClass = GRADE_COLORS[grade] || GRADE_COLORS["?"];
            return (
              <div
                key={entry.asset_id}
                className={`p-4 rounded-lg border transition ${
                  activeCitation === String(entry.number)
                    ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                    : "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50"
                }`}
              >
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="inline-flex items-center justify-center w-6 h-6 text-xs font-bold text-white bg-blue-600 rounded-full shrink-0">
                    {entry.number}
                  </span>
                  <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {entry.document_name || "Unknown source"}
                  </span>
                  {entry.evidence_grade && (
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${gradeClass}`}>
                      {grade}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
                  {entry.preview}
                </p>
                <div className="flex items-center gap-3 mt-2">
                  {entry.page_number && (
                    <p className="text-xs text-gray-400">Page {entry.page_number}</p>
                  )}
                  {entry.confidence_score != null && (
                    <p className="text-xs text-gray-400">
                      Confidence: {Math.round(entry.confidence_score * 100)}%
                    </p>
                  )}
                  {entry.relation_path && entry.relation_path !== "direct" && (
                    <p className="text-xs text-gray-400 truncate max-w-[200px]" title={entry.relation_path}>
                      {entry.relation_path}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
