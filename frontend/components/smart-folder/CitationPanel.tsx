"use client";

interface CitationEntry {
  number: number;
  asset_id: string;
  preview: string;
  document_name?: string;
  page_number?: number | null;
}

interface CitationPanelProps {
  citationIndex: Record<string, CitationEntry>;
  activeCitation: string | null;
  onClose: () => void;
}

export default function CitationPanel({ citationIndex, activeCitation, onClose }: CitationPanelProps) {
  const entries = Object.values(citationIndex).sort((a, b) => a.number - b.number);

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

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {entries.length === 0 && (
            <p className="text-sm text-gray-500 dark:text-gray-400">No citations available.</p>
          )}
          {entries.map((entry) => (
            <div
              key={entry.asset_id}
              className={`p-4 rounded-lg border transition ${
                activeCitation === String(entry.number)
                  ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                  : "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-flex items-center justify-center w-6 h-6 text-xs font-bold text-white bg-blue-600 rounded-full">
                  {entry.number}
                </span>
                <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {entry.document_name || "Unknown source"}
                </span>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
                {entry.preview}
              </p>
              {entry.page_number && (
                <p className="text-xs text-gray-400 mt-1">Page {entry.page_number}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
